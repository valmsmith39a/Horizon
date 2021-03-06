# Pre-req installations:
# https://docs.docker.com/install/linux/docker-ce/ubuntu/
# https://github.com/NVIDIA/nvidia-docker

# Usage:
#        sudo docker build -t horizon_initial_release . 2>&1 | tee stdout
#    or
#        sudo nvidia-docker build -t horizon_initial_release . 2>&1 | tee stdout
#        sudo nvidia-docker run -i -t --rm horizon_initial_release /bin/bash

# Remove all stopped Docker containers:   sudo docker rm $(sudo docker ps -a -q)
# Remove all untagged images:             sudo docker rmi $(sudo docker images -q --filter "dangling=true")

# Available versions: https://hub.docker.com/r/nvidia/cuda/
FROM ubuntu:16.04

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    git \
    libgflags-dev \
    libgoogle-glog-dev \
    libgtest-dev \
    libiomp-dev \
    libleveldb-dev \
    liblmdb-dev \
    libopencv-dev \
    libopenmpi-dev \
    libprotobuf-dev \
    libsnappy-dev \
    locales \
    openmpi-bin \
    openmpi-doc \
    protobuf-compiler \
    sudo \
    software-properties-common \
    vim \
    wget

# Sometimes needed to avoid SSL CA issues.
RUN update-ca-certificates

ENV HOME /home
WORKDIR ${HOME}/

RUN wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh && \
    chmod +x miniconda.sh && \
    ./miniconda.sh -b -p ${HOME}/miniconda && \
    rm miniconda.sh

# Setting these env var outside of the install script to ensure
# they persist in image
# (See https://stackoverflow.com/questions/33379393/docker-env-vs-run-export)
ENV PATH ${HOME}/miniconda/bin:$PATH
ENV CONDA_PATH ${HOME}/miniconda

# Switch to python 3.6 (needed for tensorboard)
RUN conda install python=3.6

# Install java and maven
RUN conda install maven openjdk
ENV JAVA_HOME ${HOME}/miniconda

# Install Spark
RUN wget http://www-eu.apache.org/dist/spark/spark-2.3.1/spark-2.3.1-bin-hadoop2.7.tgz && \
    tar -xzf spark-2.3.1-bin-hadoop2.7.tgz && \
    mv spark-2.3.1-bin-hadoop2.7 /usr/local/spark

# Install Tensorflow (for Tensorboard)
RUN conda install tensorflow

# Needed to prevent UnicodeDecodeError: 'ascii' codec can't decode byte
# when installing fairseq.
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

ENV LD_LIBRARY_PATH ${CONDA_PATH}/lib:${LD_LIBRARY_PATH}

# Install cython first to make sure new modules are compiled with the right version of cython
RUN conda install cython==0.29

# Install thrift compiler
RUN conda install thrift-cpp

ADD ./install_prereqs.sh install_prereqs.sh
ADD ./requirements.txt requirements.txt
RUN ./install_prereqs.sh
RUN rm install_prereqs.sh requirements.txt

# Define default command.
CMD ["bash"]
