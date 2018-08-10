#!/usr/bin/python

""" 
Run_long_script governs the running of long gazebo_ros_tensorflow simulations.

The core functionality lies in: 
  1. parsing the correct arguments at different levels (tensorflow dnn, gazebo environment, ros supervision)
  2. different crash handling when for instance starting gazebo / tensorflow fails

The script is organized in different steps:
1. Parsing arguments saved in a name space
2. launching ROS  and robot related parameters
3. launching tensorflow in machine (docker/singularity/virtualenv) environment
4. launching experiment with potentially autogenerated gazebo world

Exit code:
0) normal exit code
2) tensorflow stopped working
3) communication with logfolder (Opal) is blocked
4) config file is missing

Author: Klaas Kelchtermans

Dependecies: simulation_supervised, pilot, klaas_robots
"""
import rospy
import sys, os, os.path
import subprocess, shlex
import shutil
import time
import signal
import argparse
import yaml
import fnmatch
import numpy as np

# global variables for Popen objects used for terminating sessions
ros_popen = None
python_popen = None
gazebo_popen = None

crash_number = 0
run_number = 0

# Predefined functions.
def load_param_file(location):
  """Load yaml as dict and change to proper string arguments.
  Note that current implementation will by default change both --key True and --key False to --key."""
  yaml_dict={}
  with open(location, 'r') as stream:
    try:
      yaml_dict=yaml.load(stream)
    except yaml.YAMLError as exc:
      print(exc)
  yaml_str=""
  for k in yaml_dict.keys():
    if isinstance(yaml_dict[k],bool):
      yaml_str = "{0} --{1}".format(yaml_str, k)
    else:
      yaml_str = "{0} --{1} {2}".format(yaml_str, k, yaml_dict[k])
  return yaml_str

def wait_for_gazebo():
  """gazebo popen is not enough to get gzserver to stop so wait longer..."""
  p_ps = subprocess.Popen(["ps", "-ef"], stdout=subprocess.PIPE)
  p_grep = subprocess.Popen(["grep","gz"],stdin=p_ps.stdout, stdout=subprocess.PIPE)
  print("{0}: wait for gazebo".format(time.strftime("%Y-%m-%d_%I:%M:%S")))
  out = p_grep.communicate()[0]
  while "gzserver" in out:
    p_ps = subprocess.Popen(["ps", "-ef"], stdout=subprocess.PIPE)
    p_grep = subprocess.Popen(["grep","gz"],stdin=p_ps.stdout, stdout=subprocess.PIPE)
    out = p_grep.communicate()[0]
    time.sleep(0.2)
  time.sleep(1)  

def wait_for_create_dataset():
  """gazebo popen is not enough to get gzserver to stop so wait longer..."""
  p_ps = subprocess.Popen(["ps", "-ef"], stdout=subprocess.PIPE)
  p_grep = subprocess.Popen(["grep","create_dataset"],stdin=p_ps.stdout, stdout=subprocess.PIPE)
  print("{0}: wait for create_dataset".format(time.strftime("%Y-%m-%d_%I:%M:%S")))
  out = p_grep.communicate()[0]
  while "create_dataset" in out:
    p_ps = subprocess.Popen(["ps", "-ef"], stdout=subprocess.PIPE)
    p_grep = subprocess.Popen(["grep","create_dataset"],stdin=p_ps.stdout, stdout=subprocess.PIPE)
    out = p_grep.communicate()[0]
    time.sleep(0.2)  


def kill_popen(process_name, process_popen):
  """Check status, terminate popen and wait for it to stop."""
  print("{0}: terminate {1}".format(time.strftime("%Y-%m-%d_%I:%M:%S"), process_name))
  if process_popen.poll() == None:
    process_popen.terminate()
    process_popen.wait()
  
def kill_combo():
  """kill ros, python and gazebo pids and wait for them to finish"""
  global ros_popen, python_popen, gazebo_popen
  if gazebo_popen: kill_popen('gazebo', gazebo_popen)
  wait_for_gazebo()
  if python_popen: kill_popen('python', python_popen)
  if ros_popen: kill_popen('ros', ros_popen)
  time.sleep(5)

##########################################################################################################################
# STEP 1 Load Parameters

parser = argparse.ArgumentParser(description="""Run_simulation_scripts governs the running of long gazebo_ros_tensorflow simulations.
        The core functionality lies in:
        1. parsing the correct arguments at different levels (tensorflow dnn, gazebo environment, ros supervision)
        2. different crash handling when for instance starting gazebo / tensorflow fails""")

# ==========================
#   General Settings
# ==========================
parser.add_argument("--summary_dir", default='tensorflow/log/', type=str, help="Choose the directory to which tensorflow should save the summaries.")
parser.add_argument("--data_root", default='pilot_data/', type=str, help="Choose the directory to which tensorflow should save the summaries.")
parser.add_argument("--code_root", default='~', type=str, help="Choose the directory to which tensorflow should save the summaries.")
parser.add_argument("-t", "--log_tag", default='testing_online', type=str, help="LOGTAG: tag used to name logfolder.")
parser.add_argument("--data_location", default='', type=str, help="Datalocation is by default the log_tag but than in data_root instead of summary_dir, otherwise FLAG should indicate relative path to data_root.")
parser.add_argument("-n", "--number_of_runs", default=2, type=int, help="NUMBER_OF_RUNS: define the number of runs the robot will be trained/evaluated.")
parser.add_argument("-g", "--graphics", action='store_true', help="Add extra nodes for visualization e.g.: Gazebo GUI, control display, depth prediction, ...")
parser.add_argument("-e", "--evaluation", action='store_true',help="This script can launch 2 modes of experiments: training (default) or evaluation.")
parser.add_argument("--evaluate_every", default=20, type=int, help="Evaluate every N runs when training.")
parser.add_argument("-ds", "--create_dataset", action='store_true',help="In case of True, sensor data is saved.")
parser.add_argument("--save_only_success", action='store_true',help="In case of True, sensor data is saved.")
parser.add_argument("--seed", type=float, help="In case of True, sensor data is saved.")

# ==========================
#   Robot Settings
# ==========================
parser.add_argument("--robot",default='turtle_sim', type=str, help="Specify the robot configuration file: turtle_sim(default), drone_sim, turtle_real, drone_real.")

# ==========================
#   Tensorflow Settings
# ==========================
parser.add_argument("-m","--checkpoint_path", type=str, help="Specify the directory of the checkpoint of the earlier trained model.")
parser.add_argument("-pe","--python_environment",default='sing', type=str, help="Define which environment should be loaded in shell when launching tensorlfow. Possibilities: sing, docker, virtualenv.")
parser.add_argument("-pp","--python_project",default='pilot/pilot', type=str, help="Define which python module should be started with ~/tenorflow/PROJECT_NAME/main.py: q-learning/pilot, pilot/pilot, ddpg, ....")

# ==========================
#   Environment Settings
# ==========================
parser.add_argument("--reuse_default_world", action='store_true',help="reuse the default forest/canyon/sandbox instead of generating them on the fly.")
parser.add_argument("-w","--world",dest='worlds', action='append', nargs=1, help="Define different worlds: canyon, forest, sandbox, esat_v1, esat_v2, ... .")
parser.add_argument("-p","--paramfile",default='eva_params.yaml',type=str, help="Add more parameters to the command loading the DNN in tensorflow ex: eva_params.yaml or params.yaml.")
parser.add_argument("--fsm",default='nn_turtle_fsm',type=str, help="Define the fsm loaded from /simsup/config/fsm: nn_turtle_fsm, console_fsm, console_nn_db_turtle_fsm, ...")

parser.add_argument("--x_pos",default=0,type=float, help="Specify x position.")
parser.add_argument("--x_var",default=0,type=float, help="Specify variation in x position.")
parser.add_argument("--y_pos",default=0,type=float, help="Specify y position.")
parser.add_argument("--y_var",default=0,type=float, help="Specify variation in y position.")
parser.add_argument("--z_pos",default=0,type=float, help="Specify z position.")
parser.add_argument("--z_var",default=0,type=float, help="Specify variation z position.")
parser.add_argument("--yaw_or",default=1.57,type=float, help="Specify yaw orientation.")
parser.add_argument("--yaw_var",default=0,type=float, help="Specify variation in yaw orientation.")

FLAGS, others = parser.parse_known_args()
# FLAGS=parser.parse_args()

# get simulation_supervised dir
simulation_supervised_dir=subprocess.check_output(shlex.split("rospack find simulation_supervised"))[:-1]

# 3 main directories have to be defined in order to make it also runnable from a read-only system-installed singularity image.
if FLAGS.summary_dir[0] != '/':  # 1. Tensorflow log directory for saving tensorflow logs and xterm logs
  FLAGS.summary_dir=os.environ['HOME']+'/'+FLAGS.summary_dir
if FLAGS.data_root[0] != '/':  # 2. Pilot_data directory for saving data
  FLAGS.data_root=os.environ['HOME']+'/'+FLAGS.data_root
if FLAGS.code_root == '~': # 3. location for tensorflow code (and also catkin workspace though they are found with rospack)
  #no explicit directory for code is set so try to parse first from environment
  try:
    FLAGS.code_root = os.environ['CODE']
  except KeyError: # in case environment variable is not set, take home dir
    FLAGS.code_root = os.environ['HOME']

if FLAGS.log_tag == 'testing_online':
  if os.path.isdir(FLAGS.summary_dir+FLAGS.log_tag): shutil.rmtree(FLAGS.summary_dir+FLAGS.log_tag)    
  if os.path.isdir(FLAGS.data_root+FLAGS.log_tag): shutil.rmtree(FLAGS.data_root+FLAGS.log_tag)

# add default values to be able to operate
if FLAGS.worlds == None : FLAGS.worlds=['canyon']
else: #worlds are appended in a nested list... so get them out.
  worlds=[]
  for w in FLAGS.worlds: 
    if os.path.isfile(simulation_supervised_dir+'/config/environment/'+w[0]+'.yaml'):
      worlds.append(w[0])
    else:
      print("Could not find environment configuration for {}".format(w[0]))
      sys.exit(4)

  FLAGS.worlds = worlds[:]
if FLAGS.seed: np.random.seed(FLAGS.seed)
FLAGS.params=load_param_file(FLAGS.paramfile) if FLAGS.paramfile else ""

# try to extract condor host
# try:
#   FLAGS.condor_host=subprocess.check_output(shlex.split("cat $_CONDOR_JOB_AD | grep RemoteHost | head -1 | cut -d '=' -f 2 | cut -d '@' -f 2 | cut -d '.' -f 1)"))  
# except:
FLAGS.condor_host='unknown_host'

# Create main log folder
if not os.path.isdir("{0}{1}".format(FLAGS.summary_dir, FLAGS.log_tag)):
  os.makedirs("{0}{1}".format(FLAGS.summary_dir, FLAGS.log_tag))

# in case of data_creation, make data_location in ~/pilot_data
if FLAGS.create_dataset: 
  if FLAGS.data_location == "":
    FLAGS.data_location = "{0}{1}".format(FLAGS.data_root, FLAGS.log_tag)
  else:
    FLAGS.data_location = "{0}{1}".format(FLAGS.data_root, FLAGS.data_location)
  if os.path.isdir(FLAGS.data_location) and FLAGS.number_of_runs == 1:
    shutil.rmtree(FLAGS.data_location)
  if not os.path.isdir(FLAGS.data_location):
    os.makedirs(FLAGS.data_location)
  else:
    # check number of items already recorded
    if len(os.listdir(FLAGS.data_location)) >= 1:
      # in case there is already data recorded, parse the number of runs and continue from there
      last_run=sorted([d for d in os.listdir(FLAGS.data_location) if os.path.isdir("{0}/{1}".format(FLAGS.data_location,d))])[-1]
      run_number=int(last_run.split('_')[0]) +1 #assuming number occurs at first 5 digits xxxxx_name_of_data
      print("Found data from previous run so adjusted run_number to {}".format(run_number))

# display and save all settings
print("\nSettings:")
for f in FLAGS.__dict__: print("{0}: {1}".format( f, FLAGS.__dict__[f]))

with open("{0}{1}/run_conf".format(FLAGS.summary_dir, FLAGS.log_tag),'w') as c:
  c.write("Settings of Run_simulation_scripts:\n\n")
  for f in FLAGS.__dict__: c.write("{0}: {1}\n".format(f, FLAGS.__dict__[f]))


##########################################################################################################################
# STEP 2 Start ROS with ROBOT specific parameters

# ensure location for logging the xterm outputs exists.
ros_xterm_log_dir="{0}{1}/xterm_ros".format(FLAGS.summary_dir,FLAGS.log_tag)
if not os.path.isdir(ros_xterm_log_dir): os.makedirs(ros_xterm_log_dir)

def start_ros():
  """Start ros core with robot parameters loaded"""
  global ros_popen
  command="roslaunch simulation_supervised load_params.launch robot_config:={}.yaml".format(FLAGS.robot)
  xterm_log_file='{0}/xterm_ros_{1}.txt'.format(ros_xterm_log_dir,time.strftime("%Y-%m-%d_%I%M"))
  if os.path.isfile(xterm_log_file): os.remove(xterm_log_file)
  args = shlex.split("xterm -iconic -l -lf {0} -hold -e {1}".format(xterm_log_file,command))
  ros_popen = subprocess.Popen(args)
  pid_ros = ros_popen.pid
  print("\n{0}: start_ros pid {1}".format(time.strftime("%Y-%m-%d_%I:%M:%S"),pid_ros))
  time.sleep(1)
  rospy.set_param('evaluate_every',FLAGS.evaluate_every if not FLAGS.evaluation else 1)  

start_ros()

##########################################################################################################################
# STEP 3 Start tensorflow

python_xterm_log_dir="{0}{1}/xterm_python".format(FLAGS.summary_dir,FLAGS.log_tag)
if not os.path.isdir(python_xterm_log_dir): os.makedirs(python_xterm_log_dir)
  
def start_python():
  """Function that initializes python code."""
  # delete default test folder
  # if logdir already exists probably condor job is just restarted somewhere so use last saved q in case of training
  global python_popen
  if not FLAGS.evaluation:
    for f in os.listdir(FLAGS.summary_dir+FLAGS.log_tag):
      if fnmatch.fnmatch(f,"2018*"): # take only the tensorflow folders, indicated with a date tag
        if len([d for d in os.listdir(FLAGS.summary_dir+FLAGS.log_tag+'/'+f) if "checkpoint" in d]) > 0 :
          FLAGS.checkpoint_path=FLAGS.summary_dir+FLAGS.log_tag
          FLAGS.params.replace('scratch','')
          if 'continue_training' not in FLAGS.params: FLAGS.params="{0} --continue_training".format(FLAGS.params)
          break
        else:
          # in case python crashed during that run and left no more than 6 items, clean up logfolder
          shutil.rmtree(FLAGS.summary_dir+FLAGS.log_tag+'/'+f)
  
  # Add parameters
  FLAGS.log_folder = "{0}{1}/{2}_{3}".format(FLAGS.summary_dir,FLAGS.log_tag,time.strftime("%Y-%m-%d_%I%M"),'eval' if FLAGS.evaluation else 'train')
  FLAGS.params="{0} --log_tag {1[0]}{1[1]}".format(FLAGS.params, FLAGS.log_folder.partition(FLAGS.log_tag)[1:])
  if not '--online' in FLAGS.params: FLAGS.params="{0} --online".format(FLAGS.params)
  if FLAGS.checkpoint_path: FLAGS.params="{0} --checkpoint_path {1}".format(FLAGS.params, FLAGS.checkpoint_path)  
  if not FLAGS.graphics and 'dont_show_depth' not in FLAGS.params: FLAGS.params="{0} --dont_show_depth".format(FLAGS.params)

  # Create command
  command="{0}/scripts/launch_python/{1}.sh {2}/tensorflow/{3}/main.py {4}".format(simulation_supervised_dir,
                                                                                FLAGS.python_environment,
                                                                                FLAGS.code_root,
                                                                                FLAGS.python_project,
                                                                                FLAGS.params)
  print("Tensorflow command: \n {}".format(command))
  xterm_log_file='{0}/xterm_python_{1}.txt'.format(python_xterm_log_dir,time.strftime("%Y-%m-%d_%I%M"))
  if os.path.isfile(xterm_log_file): os.remove(xterm_log_file)
  args = shlex.split("xterm -l -lf {0} -hold -e {1}".format(xterm_log_file, command))
  # Execute command
  python_popen = subprocess.Popen(args)
  pid_python = python_popen.pid
  print("\n{0}: start_python pid {1}".format(time.strftime("%Y-%m-%d_%I:%M:%S"),pid_python))
  # Wait for creation of tensorflow log file to know the python node is running
  start_time = time.time()
  while(not os.path.isfile(FLAGS.log_folder+'/tf_log')):
    time.sleep(1)
    if time.time()-start_time > 5*60:
      print("{0}: Waited for 5minutes on tf_log in {2} to start, seems like tensorflow has crashed on {1} so exit with error code 2.".format(time.strftime("%Y-%m-%d_%I:%M"), FLAGS.condor_host, FLAGS.log_folder))
      kill_combo()
      sys.exit(2)

start_python()

##########################################################################################################################
# STEP 4 Start gazebo environment

# ensure location for logging the xterm outputs exists.
gazebo_xterm_log_dir="{0}{1}/xterm_gazebo".format(FLAGS.summary_dir,FLAGS.log_tag)
if not os.path.isdir(gazebo_xterm_log_dir): os.makedirs(gazebo_xterm_log_dir)


while run_number < FLAGS.number_of_runs:
  crashed=False #on this moment the run is not crashed (yet).

  # gradually build command according to parameters
  command="roslaunch simulation_supervised_demo {0}.launch".format(FLAGS.robot)
  
  # add fsm
  command="{0} fsm_config:={1}".format(command, FLAGS.fsm)
  
  # add logfolder
  command="{0} log_folder:={1}".format(command, FLAGS.log_folder)
  
  # check if this is an evaluation run and in which environment (world_name):
  evaluate=(run_number%FLAGS.evaluate_every) == 1 or FLAGS.evaluation
  command="{0} evaluate:={1}".format(command, 'true' if evaluate else 'false')
  
  world_name=FLAGS.worlds[run_number%len(FLAGS.worlds)]
  command="{0} world_name:={1}".format(command, world_name)
  
  print("\n{0}: started {3} run {1} of the {2} in {4}".format(time.strftime("%Y-%m-%d_%I:%M:%S"),
                                                          run_number+1, 
                                                          FLAGS.number_of_runs, 
                                                          'evaluation' if evaluate else 'training',
                                                          world_name))

  # in case of saving data, increment data location in ~/pilot_data
  if FLAGS.create_dataset:
    # remove if saving location already exists (probably due to crash previously)
    if os.path.isdir("{0}/{1:05d}_{2}".format(FLAGS.data_location,run_number,world_name)): shutil.rmtree("{0}/{1:05d}_{2}".format(FLAGS.data_location,run_number,world_name))
    command="{0} data_location:={1}/{2:05d}_{3} save_images:=true".format(command, FLAGS.data_location,run_number,world_name)

  # save current status of tensorflow log to compare afterwards
  if os.path.isfile(FLAGS.log_folder+'/tf_log'):
    prev_stat=subprocess.check_output(shlex.split("stat -c %Y "+FLAGS.log_folder+'/tf_log'))
  else: # we have last communication with our log folder so exit with code 2
    print("{2}: lost communication with our log folder {0} on host {1} so exit with code 3.".format(FLAGS.log_folder, FLAGS.condor_host, time.strftime("%Y-%m-%d_%I:%M:%S")))
    kill_combo()
    sys.exit(3)

  # generate world if it is possible and allowed, this also changes the loaded world file location from the default simsup_demo/worlds to log_folder
  if world_name in ['canyon', 'forest', 'sandbox'] and not FLAGS.reuse_default_world:
    generator_file="{0}/python/generators/{1}_generator.py".format(subprocess.check_output(shlex.split("rospack find simulation_supervised_tools"))[:-1],world_name)
    subprocess.Popen(shlex.split("python "+generator_file+" "+FLAGS.log_folder)).wait()
    command="{0} background:={1} world_file:={2}".format(command, FLAGS.log_folder+'/'+world_name+'.png', FLAGS.log_folder+'/'+world_name+'.world')
  elif world_name == 'canyon':
    # reuse default 20 evaluation canyons
    world_file='{0}/../simulation_supervised_demo/worlds/canyon_evaluation/{1:05d}_canyon.world'.format(simulation_supervised_dir,run_number%20)
    world_image='{0}/../simulation_supervised_demo/worlds/canyon_evaluation/{1:05d}_canyon.png'.format(simulation_supervised_dir,run_number%20)
    command="{0} background:={1} world_file:={2}".format(command, world_image, world_file)

  # clean up gazebo ros folder every now and then
  if run_number%50 == 0 : shutil.rmtree("{0}/.gazebo/log".format(os.environ['HOME']),ignore_errors=True)
    
  # set correct x,y,z position, yaw orientation with variations
  command="{0} x:={1}".format(command,FLAGS.x_pos + np.random.uniform(-FLAGS.x_var,FLAGS.x_var))
  command="{0} y:={1}".format(command,FLAGS.y_pos + np.random.uniform(-FLAGS.y_var,FLAGS.y_var))
  command="{0} starting_height:={1}".format(command,FLAGS.z_pos + np.random.uniform(-FLAGS.z_var,FLAGS.z_var))
  command="{0} Yspawned:={1}".format(command,FLAGS.yaw_or + np.random.uniform(-FLAGS.yaw_var,FLAGS.yaw_var))

  # graphics
  command="{0} graphics:={1}".format(command,'true' if FLAGS.graphics else 'false')

  # clean up potential previous pid file
  pid_file = FLAGS.log_folder+'/.pid'
  if os.path.isfile(pid_file): os.remove(pid_file)

  # Execute command
  print "gazebo_command: ",command
  xterm_log_file='{0}/xterm_gazebo_{1}.txt'.format(gazebo_xterm_log_dir,time.strftime("%Y-%m-%d_%I-%M-%S"))
  args = shlex.split("xterm -iconic -l -lf {0} -hold -e {1}".format(xterm_log_file,command))
  gazebo_popen = subprocess.Popen(args)
  pid_gazebo = gazebo_popen.pid
  print("\n{0}: start_gazebo pid {1}".format(time.strftime("%Y-%m-%d_%I:%M:%S"),pid_gazebo))

  # Write xterm pid away
  pidf = open(pid_file,'w')
  pidf.write("{0}".format(pid_gazebo))
  pidf.close()
  
  # wait for popen to terminate
  start_time=time.time()
  time_spend=0
  while gazebo_popen.poll() == None:
    # Check on job suspension: 
    # if between last update and now has been more than 30 seconds (should be less than 0.1s)
    if time.time() - start_time - time_spend > 30:
      print("{0}: Job got suspended.".format(time.strftime("%Y-%m-%d_%I:%M:%S")))
      time.sleep(30) #wait for big tick to update
      start_time=time.time()
    else:
      time_spend=time.time() - start_time
    if time_spend > 60*9 and FLAGS.number_of_runs != 1: #don't interupt if this is a single run
      print("{0}: running more than 9minutes so crash.".format(time.strftime("%Y-%m-%d_%I:%M:%S")))
      crashed=True
      crash_number+=1
      if crash_number < 3:
        kill_popen('gazebo', gazebo_popen)
      else:
        print("{0}: crashed for third time so restart everything.".format(time.strftime("%Y-%m-%d_%I:%M:%S")))
        kill_combo()
        start_ros()
        start_python()
        crash_number = 0
    time.sleep(0.1)

  # gazebo_popen.poll() == 15 --> killed by script
  # gazebo_popen.poll() == 0 --> killed by user 
  # gazebo_popen.poll() == 15 --> killed by fsm
  if not crashed and gazebo_popen.poll() != 0 and 'nn' in FLAGS.fsm:
    # wait for tf_log and stop in case of no tensorflow communication
    if os.path.isfile(FLAGS.log_folder+'/tf_log'):
      current_stat=subprocess.check_output(shlex.split("stat -c %Y "+FLAGS.log_folder+'/tf_log'))
      start_time=time.time()
      print("{0}: waiting for tf_log.".format(time.strftime("%Y-%m-%d_%I:%M:%S")))
      while current_stat == prev_stat:
        current_stat=subprocess.check_output(shlex.split("stat -c %Y "+FLAGS.log_folder+'/tf_log'))
        time.sleep(1)
        if time.time()-start_time > 8*60:
          print("{0}: waited for 8minutes on tf_log to finish training so something went wrong on {1} exit with code 2.".format(time.strftime("%Y-%m-%d_%I:%M:%S"), FLAGS.condor_host))
          kill_combo()
          sys.exit(2)
    else:
      print("{2}: we have lost communication with our log folder {0} on host {1} so exit with code 3.".format(FLAGS.log_folder, FLAGS.condor_host, time.strftime("%Y-%m-%d_%I:%M:%S")))
      kill_combo()
      sys.exit(3)
    # check for success or failure from log file
  if not crashed:
    # increment the run numbers in case of no gazebo crash.
    success=''
    try:
      success = open("{0}/log".format(FLAGS.log_folder),'r').readlines()[-1][:-1]
      # success = subprocess.check_output(shlex.split("tail -1 {0}/log".format(FLAGS.log_folder)))
    except:
      pass
    else:
      print("\n{0}: ended run {1} with {2}".format(time.strftime("%Y-%m-%d_%I:%M:%S"), run_number+1, success))
    if FLAGS.save_only_success and FLAGS.create_dataset and 'success' not in success:
      print("no success, so retry.")
      # data folder will be removed when starting up new gazebo simulation.
    else:
      run_number+=1
  # continue with next run if gazebo if fully killed:
  wait_for_gazebo()
  # wait_for_create_dataset()

# after all required runs are finished
kill_combo()
print("\n{0}: done.".format(time.strftime("%Y-%m-%d_%I:%M:%S")))

