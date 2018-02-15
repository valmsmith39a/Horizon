from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import numpy as np
import six

from caffe2.proto import caffe2_pb2
from caffe2.python.predictor.predictor_exporter import \
    save_to_db, load_from_db, prepare_prediction_net
from caffe2.python import workspace
from caffe2.python.predictor_constants import predictor_constants
from caffe2.python.predictor.predictor_py_utils import GetBlobs

from ml.rl.preprocessing.preprocessor_net import (
    PreprocessorNet, MISSING_VALUE, sort_features_by_normalization
)

import logging
logger = logging.getLogger(__name__)


class RLPredictor(object):
    normalized_input = "PredictorInput"

    def __init__(self, net, parameters):
        """

        :param net caffe2 net used for prediction
        :param input_blobs caffe2 blobs used as input
        :param output_blobs caffe2 blobs used as output
        :param parameters caffe2 blobs used as network paramers
        """
        self._net = net
        self._input_blobs = [
            'input/float_features.lengths', 'input/float_features.keys',
            'input/float_features.values'
        ]
        self._output_blobs = [
            'output/string_weighted_multi_categorical_features.keys',
            'output/string_weighted_multi_categorical_features.lengths',
            'output/string_weighted_multi_categorical_features.values.keys',
            'output/string_weighted_multi_categorical_features.values.lengths',
            'output/string_weighted_multi_categorical_features.values.values',
        ]
        self._parameters = parameters

    def predict(self, examples):
        """ Returns values for each state
        :param examples A list of feature -> value dict examples
        """
        workspace.FeedBlob(
            'input/float_features.lengths',
            np.array([len(e) for e in examples], dtype=np.int32)
        )
        workspace.FeedBlob(
            'input/float_features.keys',
            np.array([list(e.keys())
                      for e in examples], dtype=np.int32).flatten()
        )
        workspace.FeedBlob(
            'input/float_features.values',
            np.array([list(e.values())
                      for e in examples], dtype=np.float32).flatten()
        )
        workspace.RunNet(self._net)

        output_lengths = workspace.FetchBlob(
            'output/string_weighted_multi_categorical_features.values.lengths'
        )
        output_names = workspace.FetchBlob(
            'output/string_weighted_multi_categorical_features.values.keys'
        )
        output_values = workspace.FetchBlob(
            'output/string_weighted_multi_categorical_features.values.values'
        )

        results = []

        cursor = 0
        for length in output_lengths:
            cursor_begin = cursor
            cursor_end = cursor_begin + length
            cursor = cursor_end

            result = {}
            for x in range(cursor_begin, cursor_end):
                result[output_names[x].decode("utf-8")] = output_values[x]
            results.append(result)

        return results

    def get_predictor_export_meta(self):
        """
        Returns a PredictorExportMeta object
        """
        pass

    def save(self, db_path, db_type):
        """ Saves network to db

        :param db_path see save_to_db
        :param db_type see save_to_db
        """
        meta = self.get_predictor_export_meta()
        for parameter in self._parameters:
            parameter_data = workspace.FetchBlob(parameter)
            logger.info("DATA TYPE " + parameter_data.dtype.kind)
            if parameter_data.dtype.kind in {'U', 'S', 'O'}:
                continue  # Don't bother checking string blobs for nan
            logger.info("Checking parameter {} for nan".format(parameter))
            if np.any(np.isnan(parameter_data)):
                logger.info("WARNING: parameter {} is nan".format(parameter))
        save_to_db(db_type, db_path, meta)

    @classmethod
    def load(cls, db_path, db_type):
        """ Creates Predictor by loading from a database

        :param db_path see load_from_db
        :param db_type see load_from_db
        """
        net = prepare_prediction_net(db_path, db_type)
        meta = load_from_db(db_path, db_type)
        parameters = GetBlobs(meta, predictor_constants.PARAMETERS_BLOB_TYPE)
        return cls(net, parameters)

    def analyze(self, named_features):
        print("==================== Model parameters =========================")
        previous_workspace = workspace.CurrentWorkspace()
        workspace.SwitchWorkspace(self._workspace_id)

        for parameter in self._parameters:
            parameter_value = workspace.FetchBlob(parameter)
            print()
            print("Parameter {}:".format(parameter))
            print(parameter_value)
            print()
            print()

        print()
        print("==================== Output ============================")
        for _ in range(3):
            score = self.predict(named_features)
            print(score)
        print()

        print("==================== Input =========================")
        for name, value in six.iteritems(named_features):
            print("Feature {}: {}".format(name, value))

        print()
        print("==================== Normalized Input =========================")
        for name in named_features:
            norm_blob_value = workspace.FetchBlob(name + "_preprocessed")
            print("Normalized Feature {}: {}".format(name, norm_blob_value))

        workspace.SwitchWorkspace(previous_workspace)

    @classmethod
    def _sparse_to_normalized_dense(
        cls, net, normalization_parameters, normalization_prefix
    ):
        parameters = []
        sorted_features, feature_starts = sort_features_by_normalization(
            normalization_parameters
        )

        int_features = [int(feature) for feature in sorted_features]
        workspace.FeedBlob(
            'input/float_features.lengths', np.zeros(1, dtype=np.int32)
        )
        workspace.FeedBlob(
            'input/float_features.keys', np.zeros(1, dtype=np.int32)
        )
        workspace.FeedBlob(
            'input/float_features.values', np.zeros(1, dtype=np.float32)
        )
        dense_input = net.NextBlob('dense_input')
        workspace.FeedBlob(dense_input, np.zeros(1, dtype=np.float32))
        default_input_value = net.NextBlob('default_input_value')
        workspace.FeedBlob(
            default_input_value, np.array([MISSING_VALUE], dtype=np.float32)
        )
        parameters.append(default_input_value)
        net.GivenTensorFill(
            [], [default_input_value], shape=[], values=[MISSING_VALUE]
        )
        net.SparseToDenseMask(
            [
                'input/float_features.keys',
                'input/float_features.values',
                default_input_value,
                'input/float_features.lengths',
            ], [dense_input],
            mask=int_features
        )
        normalized_dense_matrix = net.NextBlob('normalized_dense_matrix')
        normalizer = PreprocessorNet(net, True)
        parameters = list(normalizer.parameters[:])
        normalized_dense_matrix, new_parameters = normalizer.normalize_dense_matrix(
            dense_input, sorted_features, normalization_parameters,
            normalization_prefix
        )
        parameters.extend(new_parameters)
        return normalized_dense_matrix, parameters

    @classmethod
    def _forward_pass(cls, model, trainer, normalized_dense_matrix, actions):
        net = model.net
        parameters = []
        q_values = "q_values"
        workspace.FeedBlob(q_values, np.zeros(1, dtype=np.float32))
        trainer.build_predictor(model, normalized_dense_matrix, q_values)
        parameters.extend(model.GetAllParams())

        action_names = net.NextBlob("action_names")
        parameters.append(action_names)
        workspace.FeedBlob(action_names, np.array(actions))
        action_range = net.NextBlob("action_range")
        parameters.append(action_range)
        workspace.FeedBlob(action_range, np.array(list(range(len(actions)))))

        output_shape = net.NextBlob("output_shape")
        workspace.FeedBlob(output_shape, np.zeros(1, dtype=np.int64))
        net.Shape([q_values], [output_shape])
        output_shape_row_count = net.NextBlob("output_shape_row_count")
        net.Slice(
            [output_shape], [output_shape_row_count], starts=[0], ends=[1]
        )

        output_row_shape = net.NextBlob("output_row_shape")
        workspace.FeedBlob(output_row_shape, np.zeros(1, dtype=np.int64))
        net.Slice([q_values], [output_row_shape], starts=[0, 0], ends=[-1, 1])

        output_feature_keys = 'output/string_weighted_multi_categorical_features.keys'
        workspace.FeedBlob(output_feature_keys, np.zeros(1, dtype=np.int64))
        output_feature_keys_matrix = net.NextBlob('output_feature_keys_matrix')
        net.ConstantFill(
            [output_row_shape], [output_feature_keys_matrix],
            value=0,
            dtype=caffe2_pb2.TensorProto.INT64
        )
        net.FlattenToVec(
            [output_feature_keys_matrix],
            [output_feature_keys],
        )

        output_feature_lengths = \
            'output/string_weighted_multi_categorical_features.lengths'
        workspace.FeedBlob(output_feature_lengths, np.zeros(1, dtype=np.int32))
        output_feature_lengths_matrix = net.NextBlob(
            'output_feature_lengths_matrix'
        )
        net.ConstantFill(
            [output_row_shape], [output_feature_lengths_matrix],
            value=1,
            dtype=caffe2_pb2.TensorProto.INT32
        )
        net.FlattenToVec(
            [output_feature_lengths_matrix],
            [output_feature_lengths],
        )

        output_keys = 'output/string_weighted_multi_categorical_features.values.keys'
        workspace.FeedBlob(output_keys, np.array(['a']))
        net.Tile([action_names, output_shape_row_count], [output_keys], axis=1)

        output_lengths_matrix = net.NextBlob('output_lengths_matrix')
        net.ConstantFill(
            [output_row_shape], [output_lengths_matrix],
            value=len(actions),
            dtype=caffe2_pb2.TensorProto.INT32
        )
        output_lengths = \
            'output/string_weighted_multi_categorical_features.values.lengths'
        workspace.FeedBlob(output_lengths, np.zeros(1, dtype=np.int32))
        net.FlattenToVec(
            [output_lengths_matrix],
            [output_lengths],
        )

        output_values = \
            'output/string_weighted_multi_categorical_features.values.values'
        workspace.FeedBlob(output_values, np.array([1.0]))
        net.FlattenToVec([q_values], [output_values])
        return parameters