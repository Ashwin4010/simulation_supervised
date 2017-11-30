#!/bin/bash
export PYTHONPATH=$HOME/tensorflow/pilot:\
$HOME/drone_ws/devel/lib/python2.7/dist-packages:\
/opt/ros/kinetic/lib/python2.7/dist-packages:\
$HOME/simsup_ws/devel/lib/python2.7/dist-packages:\
/usr/lib/python2.7/dist-packages:\
/usr/local/lib/python2.7/dist-packages
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/cuda-8.0/lib64:/usr/local/cudnn/lib64:/usr/local/nvidia/lib64
cd $HOME/tensorflow/pilot/pilot
python_command="python main.py --offline False  $@"
echo $python_command
$python_command

