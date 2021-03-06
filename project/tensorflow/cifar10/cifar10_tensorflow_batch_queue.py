import io

import gzip
import os
import re
import sys
import tarfile

from datetime import datetime, date
import time
import urllib.request

import calendar

import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from scipy import ndimage

import tensorflow as tf
from tensorflow.models.image.cifar10 import cifar10_input

import argparse
from collections import namedtuple


import seaborn as sns
sns.set_style("darkgrid")
plt.rcParams['figure.figsize'] = (10.0, 8.0) # set default size of plots
plt.rcParams['image.interpolation'] = 'nearest'
plt.rcParams['image.cmap'] = 'gray'

from sklearn.metrics import confusion_matrix
classes = ['plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck']

# plt.get_cmap('gray')
def plot_confusion_matrix(cm, title='Confusion matrix', cmap=plt.cm.Blues, labels=None):
  if labels is None:
    labels = list(range(len(cm)))
  fig = plt.figure()
  plt_img = plt.imshow(cm, interpolation='nearest', cmap=cmap)
  fig.colorbar(plt_img)
  plt.title(title)
  tick_marks = np.arange(len(labels))
  plt.xticks(tick_marks, labels, rotation=45)
  plt.yticks(tick_marks, labels)
  plt.grid(b='off')
  plt.tight_layout()
  plt.ylabel('True label')
  plt.xlabel('Predicted label')
  #plt.colorbar()
  buf = io.BytesIO()
  plt.savefig(buf, format='png')
  buf.seek(0)
  test_image = np.array(ndimage.imread(buf))
  plt.close()
  return test_image[np.newaxis,:]

IMAGE_SIZE = 32
NUM_CLASSES = 10
BATCH_SIZE = 512

LOSSES_COLLECTION  = 'regularizer_losses'
DEFAULT_REG_WEIGHT =  1e-1

NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN = 50000
NUM_EXAMPLES_PER_EPOCH_FOR_EVAL = 10000
DATA_URL = 'http://www.cs.toronto.edu/~kriz/cifar-10-binary.tar.gz'


def maybe_download_and_extract(data_dir):
  """Download and extract the tarball from Alex's website."""
  dest_directory = data_dir
  if not os.path.exists(dest_directory):
    os.makedirs(dest_directory)
  filename = DATA_URL.split('/')[-1]
  filepath = os.path.join(dest_directory, filename)
  if not os.path.exists(filepath):
    def _progress(count, block_size, total_size):
      sys.stdout.write('\r>> Downloading %s %.1f%%' % (filename,
          float(count * block_size) / float(total_size) * 100.0))
      sys.stdout.flush()
    filepath, _ = urllib.request.urlretrieve(DATA_URL, filepath, _progress)
    print()
    statinfo = os.stat(filepath)
    print('Successfully downloaded', filename, statinfo.st_size, 'bytes.')
    tarfile.open(filepath, 'r:gz').extractall(dest_directory)

def activation_summaries(activation, name):
  #might want to specify the activation type (since min will always be 0 for ReLU)
  with tf.name_scope("activation_summaries"):
    mean = tf.reduce_mean(activation)
    tf.summary.histogram(name + '/activations', activation)
    tf.summary.scalar(name + '/sparsity', tf.nn.zero_fraction(activation))
    with tf.name_scope('stddev'):
      stddev = tf.sqrt(tf.reduce_sum(tf.square(activation - mean)))
    tf.summary.scalar('stddev/' + name, stddev)
    tf.summary.scalar('max/' + name, tf.reduce_max(activation))
    tf.summary.scalar('min/' + name, tf.reduce_min(activation))

def variable_summaries(variable, name):
  with tf.name_scope("variable_summaries"):
    mean = tf.reduce_mean(variable)
    tf.summary.histogram(name + '/variable_hist', variable)
    with tf.name_scope('stddev'):
      stddev = tf.sqrt(tf.reduce_sum(tf.square(variable - mean)))
    tf.summary.scalar('stddev/' + name, stddev)
    tf.summary.scalar('max/' + name, tf.reduce_max(variable))
    tf.summary.scalar('min/' + name, tf.reduce_min(variable))

#reg_placeholder = tf.placeholder(dtype=tf.float32, shape=[1])
## may want to add this to the inputs for rcl (and inference methods)
# with tf.op_scope([tensor], scope, 'L2Loss'):
#     weight = tf.convert_to_tensor(weight,
#                               dtype=tensor.dtype.base_dtype,
#                               name='loss_weight')
#     loss = tf.mul(weight, tf.nn.l2_loss(tensor), name='value')
#     tf.add_to_collection(LOSSES_COLLECTION, loss)
#     return loss


# IDEA: construct validation network (reuses parameters)
#       construct train network
#       construct visualization tool
#       construct weight reduction test

#probably need to change for validation
# so: it should be train_layer
# validation_layer = tf.get_variable("W", resuse=True)

def get_cifar10_filenames(data_dir):
  data_dir += "/cifar-10-batches-bin"
  filenames = [os.path.join(data_dir, 'data_batch_%d.bin' % i)
               for i in range(1, 6)]
  for f in filenames:
    if not tf.gfile.Exists(f):
      raise ValueError('Failed to find file: ' + f)
  return filenames

def get_image(filename_queue):
  #CIFAR10Record is a 'C struct' bundling tensorflow input data
  class CIFAR10Record(object):
    pass
  #
  result = CIFAR10Record()
  label_bytes = 1  # 2 for CIFAR-100
  result.height = 32
  result.width = 32
  result.depth = 3
  image_bytes = result.height * result.width * result.depth
  # Every record consists of a label followed by the image, with a
  # fixed number of bytes for each.
  record_bytes = label_bytes + image_bytes

  # Read a record, getting filenames from the filename_queue.  No
  # header or footer in the CIFAR-10 format, so we leave header_bytes
  # and footer_bytes at their default of 0.
  reader = tf.FixedLengthRecordReader(record_bytes=record_bytes)
  result.key, value = reader.read(filename_queue)

  # Convert from a string to a vector of uint8 that is record_bytes long.
  record_bytes = tf.decode_raw(value, tf.uint8)

  # The first bytes represent the label, which we convert from uint8->int32.
  result.label = tf.cast(
      tf.slice(record_bytes, [0], [label_bytes]), tf.int32)

  # The remaining bytes after the label represent the image, which we reshape
  # from [depth * height * width] to [depth, height, width].
  depth_major = tf.reshape(tf.slice(record_bytes, [label_bytes], [image_bytes]),
                           [result.depth, result.height, result.width])
  # Convert from [depth, height, width] to [height, width, depth].
  result.uint8image = tf.transpose(depth_major, [1, 2, 0])
  return result

def generate_batch(image, label, min_queue_examples, batch_size=BATCH_SIZE, shuffle=True):
  num_preprocess_threads = 4
  if shuffle:
    images, label_batch = tf.train.shuffle_batch(
        [image, label],
        batch_size=batch_size,
        num_threads=num_preprocess_threads,
        capacity=min_queue_examples + 3 * batch_size,
        min_after_dequeue=min_queue_examples)
  else:
    images, label_batch = tf.train.batch(
        [image, label],
        batch_size=batch_size,
        num_threads=num_preprocess_threads,
        capacity=min_queue_examples + 3 * batch_size)

  # Display the training images in the visualizer.
  tf.summary.image('images', images)

  return images, tf.reshape(label_batch, [batch_size])


def read_cifar10(data_dir, image_size=IMAGE_SIZE, batch_size=BATCH_SIZE):
  filenames = get_cifar10_filenames(data_dir)
  filename_queue = tf.train.string_input_producer(filenames)
  read_input = get_image(filename_queue)

  reshaped_image = tf.cast(read_input.uint8image, tf.float32)
  distorted_image = tf.image.random_flip_left_right(reshaped_image)
  distorted_image = tf.image.random_brightness(distorted_image,
                                               max_delta=63)
  distorted_image = tf.image.random_contrast(distorted_image,
                                             lower=0.2, upper=1.8)

  float_image = tf.image.per_image_standardization(distorted_image)

  min_fraction_of_examples_in_queue = 0.4
  min_queue_examples = int(NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN *
                           min_fraction_of_examples_in_queue)
  print('Filling queue with %d CIFAR images before starting to train. '
        'This will take a few minutes.' % min_queue_examples)
  return generate_batch(float_image, read_input.label, min_queue_examples, batch_size, shuffle=True)


#initializer=tf.contrib.layers.xavier_initializer()
#tf.contrib.layers.xavier_initializer_conv2d
def model(images):
  pass


#conv1_weights = tf.Variable(tf.random_normal([5, 5, 32, 32]), name="conv1_weights")
#alternate way of doing it

def weight_decay(layer_weights, wd=0.99):
  layer_weights = tf.mul(wd, layer_weights)
  return layer_weights

def conv_relu_eval_model(layer_in, name):
  with tf.variable_scope(name, reuse=True) as scope:
    kernel = tf.get_variable("W")
    bias = tf.get_variable("b")
    conv = tf.nn.conv2d(layer_in, kernel, strides=[1,1,1,1], padding='SAME')
    layer = tf.nn.relu(conv + bias)
  return layer

sub = None

def conv_relu(layer_in, kernel_shape, bias_shape, name):
  global sub
  with tf.variable_scope(name) as scope:
    kernel = tf.get_variable("W",
                             shape=kernel_shape,
                             initializer=tf.contrib.layers.xavier_initializer_conv2d())
    bias = tf.get_variable("b", shape=bias_shape, initializer=tf.constant_initializer(0.))
    conv = tf.nn.conv2d(layer_in, kernel, strides=[1,1,1,1], padding='SAME')
    layer = tf.nn.relu(conv + bias)
    #variable_summaries(bias, bias.name)
    variable_summaries(kernel, kernel.name)
    activation_summaries(layer, layer.name)
    # layer = tf.nn.lrn(layer, 4, bias=1.0, alpha=0.001 / 9.0, beta=0.75, name='norm')
  return layer

def fcl_relu_eval_model(layer_in, name):
  with tf.variable_scope(name, reuse=True) as scope:
    dim = np.prod(layer_in.get_shape().as_list()[1:])
    reshape = tf.reshape(layer_in, [-1, dim])
    weights = tf.get_variable("W_fcl")
    bias = tf.get_variable("b_fcl")
    layer = tf.nn.relu(tf.matmul(reshape, weights) + bias)
    layer = tf.nn.dropout(layer, 1.0)
  return layer

def fcl_relu(layer_in, output_size, name,
             regularizer_weight=None, keep_prob=None,
             loss_collection=LOSSES_COLLECTION):
  with tf.variable_scope(name) as scope:
    #batch_size = layer_in.get_shape().as_list()[0]
    #dim = np.prod(layer_in.get_shape().as_list()[1:])
    #reshape = tf.reshape(layer_in, [-1, dim])
    batch_size = layer_in.get_shape().as_list()[0]
    reshape = tf.reshape(layer_in, [batch_size, -1])
    dim = reshape.get_shape()[1].value
    print(dim,output_size)
    weights = tf.get_variable("W_fcl",
                              shape=[dim, output_size],
                              initializer=tf.contrib.layers.xavier_initializer())
    bias = tf.get_variable("b_fcl",
                           shape=[output_size],
                           initializer=tf.constant_initializer(0.))
    if keep_prob is None:
      keep_prob = 1.
    layer = tf.nn.relu(tf.matmul(reshape, weights) + bias, name=scope.name + "_activation")
    layer = tf.nn.dropout(layer, keep_prob)
    variable_summaries(weights, weights.name)
    #variable_summaries(bias, bias.name)
    activation_summaries(layer, layer.name)
    if regularizer_weight is None:
      regularizer_weight = DEFAULT_REG_WEIGHT
    regularizer_loss = tf.mul(regularizer_weight, tf.nn.l2_loss(weights))
    tf.add_to_collection(loss_collection, regularizer_loss)
  return layer

def inference_eval_model(images,
                         classes = NUM_CLASSES,
                         model_name="model_1"):
  with tf.variable_scope(model_name, reuse=True) as model_scope:
    layer = conv_relu_eval_model(images, "conv_1")
    layer = conv_relu_eval_model(layer, "conv_2")
    layer = conv_relu_eval_model(layer, "conv_3")
    layer = conv_relu_eval_model(layer, "conv_4")
    layer = conv_relu_eval_model(layer, "conv_5")
    layer = conv_relu_eval_model(layer, "conv_6")
    layer = conv_relu_eval_model(layer, "conv_7")
    layer = fcl_relu_eval_model(layer, "fcl_1")
    with tf.variable_scope('pre_softmax_linear', reuse=True) as scope:
      weights = tf.get_variable('weights')
      biases = tf.get_variable('biases')
      pre_softmax_linear = tf.add(tf.matmul(layer, weights), biases, name=scope.name)
  return pre_softmax_linear

def predict_eval_model(logits):
  return tf.argmax(logits, dimension=1)

def accuracy_eval_model(logits, y_label):
  return tf.reduce_mean(tf.cast(tf.equal(tf.argmax(logits,1), tf.cast(y_label, tf.int64)), tf.float32))

def inference(images,
              classes = NUM_CLASSES,
              keep_prob=None,
              regularizer_weight=None,
              loss_collection=LOSSES_COLLECTION,
              model_name="model_1"):
  with tf.variable_scope(model_name) as model_scope:
    layer = conv_relu(images, [5,5,3,128], [128], "conv_1")
    layer = conv_relu(layer,  [3,3,128,128], [128], "conv_2")
    layer = conv_relu(layer,  [3,3,128,128], [128], "conv_3")
    layer = conv_relu(layer,  [3,3,128,128], [128], "conv_4")
    layer = conv_relu(layer,  [3,3,128,128], [128], "conv_5")
    layer = conv_relu(layer,  [3,3,128,128], [128], "conv_6")
    layer = conv_relu(layer,  [3,3,128,256], [256], "conv_7")
    # layer = conv_relu(layer,  [5,5,64,64], [64], "conv_4")
    # layer = conv_relu(layer,  [3,3,128,128], [128], "conv_5")
    # layer = conv_relu(layer,  [3,3,128,128], [128], "conv_6")
    last_conv_layer = layer
    print(last_conv_layer.get_shape())
    layer = fcl_relu(layer, 128, "fcl_1", keep_prob=keep_prob)

    with tf.variable_scope('pre_softmax_linear') as scope:
      weights = tf.get_variable('weights',
                                shape=[128, classes],
                                initializer=tf.contrib.layers.xavier_initializer())
      biases = tf.get_variable('biases',
                               shape=[classes],
                               initializer=tf.constant_initializer(0.))
      pre_softmax_linear = tf.add(tf.matmul(layer, weights), biases, name=scope.name)
      if keep_prob is None:
        keep_prob = 1.
      pre_softmax_linear = tf.nn.dropout(pre_softmax_linear, keep_prob)
      variable_summaries(weights, weights.name)
      #variable_summaries(biases, biases.name)
      #activation_summaries(pre_softmax_linear, pre_softmax_linear.name)
      if regularizer_weight is None:
        regularizer_weight = DEFAULT_REG_WEIGHT
      regularizer_loss = tf.mul(regularizer_weight, tf.nn.l2_loss(weights))
      tf.add_to_collection(loss_collection, regularizer_loss)
  grad_image_placeholder = tf.placeholder(dtype=tf.float32, shape=last_conv_layer.get_shape())
  grad_image = tf.gradients(last_conv_layer, [images], grad_image_placeholder)
  print(grad_image[0].get_shape())
  return pre_softmax_linear, grad_image[0], grad_image_placeholder

def predict(logits):
  return tf.argmax(logits, dimension=1)

def loss(logits, labels):
  labels = tf.cast(labels, tf.int64)
  cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(
      logits=logits, labels=labels, name='cross_entropy_per_example')
  cross_entropy_mean = tf.reduce_mean(cross_entropy, name='cross_entropy')

  # The total loss is defined as the cross entropy loss
  return cross_entropy_mean

INITIAL_LEARNING_RATE = 0.03
LEARNING_RATE_DECAY_FACTOR = 0.80
DROPOUT_KEEPPROB = 0.9
NUM_EPOCHS_PER_DECAY = 20
MAX_STEPS = 100000

DECAY_STEPS = NUM_EPOCHS_PER_DECAY * (NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN // BATCH_SIZE)
#150 is roughly the number of batches per epoch
#40,000/256 ~ 150

parser = argparse.ArgumentParser(description='CIFAR-10 Training', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('--learning_rate', default=INITIAL_LEARNING_RATE,
  type=float, nargs='?', help='Initial Learning Rate;')
parser.add_argument('--decay_rate', default=LEARNING_RATE_DECAY_FACTOR,
  type=float, nargs='?', help='Learning Rate Decay Factor;')#alternative %(default) in help string
parser.add_argument('--keep_prob', default=DROPOUT_KEEPPROB, type=float, nargs='?',
  help='Probablity to keep a neuron in the Full Connected Layers;')
parser.add_argument('--max_steps', type=int, default=MAX_STEPS, nargs='?',
  help='Maximum number of batches to run;')
parser.add_argument('--lr_decay_time', type=int, default=NUM_EPOCHS_PER_DECAY, nargs='?',
  help='Number of Epochs till LR decays;')
parser.add_argument('--regularization_weight', type=float, default=DEFAULT_REG_WEIGHT,
  nargs='?', help='Regularization weight (l2 regularization);')
parser.add_argument('--batch_size', type=int, default=BATCH_SIZE,
  nargs='?', help='Batch size;')
parser.add_argument('--lr_momentum', type=float, default=0.95, nargs='?', help='SGD Momentum Parameter;')
##
# Add device placement (0,1)?
# Add Seed?
##

##
# Add classwise scalars
##

GradOpt    = tf.train.GradientDescentOptimizer
AdagradOpt = tf.train.AdagradDAOptimizer
MomOpt     = tf.train.MomentumOptimizer
AdamOpt    = tf.train.AdamOptimizer
RMSOpt     = tf.train.RMSPropOptimizer

opt_to_name = { GradOpt : "grad", AdagradOpt : "Adagrad",
                MomOpt  : "momentum", AdamOpt : "ADAM",
                RMSOpt  : "RMSProp"
               }

#probably should pass in the optimizer to be used:
# tf.train.GradientDescentOptimizer
# tf.train.AdagradDAOptimizer
# tf.train.MomentumOptimizer
# tf.train.AdamOptimizer
# tf.train.FtrlOptimizer
# tf.train.ProximalGradientDescentOptimizer
# tf.train.ProximalAdagradOptimizer
# tf.train.RMSPropOptimizer

## BATCH NORM
# tf.contrib.layers.batch_norm
# batch_norm

#probably should pass in a momentum parameters
def train(total_loss, global_step,
          learning_rate=INITIAL_LEARNING_RATE,
          decay_steps=DECAY_STEPS,
          lr_rate_decay_factor=LEARNING_RATE_DECAY_FACTOR):
  lr = tf.train.exponential_decay(learning_rate,
                                  global_step,
                                  decay_steps,#number of steps required for it to decay
                                  lr_rate_decay_factor,
                                  staircase=True)

  tf.summary.scalar('learning_rate', lr)

  # with tf.control_dependencies([total_loss]):
  #   opt = tf.train.AdamOptimizer(lr)
  #   grads = opt.compute_gradients(total_loss)

  # #apply the gradients
  # apply_gradient_op = opt.apply_gradients(grads, global_step=global_step)

  # for grad, var in grads:
  #   if grad is not None:
  #     tf.histogram_summary(var.op.name + "/gradients", grad)

  # with tf.control_dependencies([apply_gradient_op]):
  #   train_op = tf.no_op(name="train")

  opt = tf.train.GradientDescentOptimizer(lr).minimize(total_loss, global_step=global_step)
  # grads = opt.compute_gradients(total_loss)

  return opt

#REFACTOR IDEA:
# (*) get_args() [ should be in main ? ];
# (0) load_data [ ... ];
# (1) build [constructs the graph], including placeholders and variables
# (2) train [generates training op]
# (3) generate parameters for two runs (one on each GPU)
# (4) runs [feeds and runs ops]

def main():
  #parser.print_help()
  args = parser.parse_args()
  print(args)
  print("Loading Data;")

  lr = args.learning_rate#INITIAL_LEARNING_RATE
  reg_weight = args.regularization_weight
  kp = args.keep_prob
  max_steps = args.max_steps
  decay_rate = args.decay_rate
  lr_decay_time = args.lr_decay_time
  batch_size = args.batch_size

  data_dir = "cifar10_images"
  train_dir = "cifar10_results/batch/"
  maybe_download_and_extract(data_dir=data_dir)
  if tf.gfile.Exists(train_dir):
    tf.gfile.DeleteRecursively(train_dir)
  tf.gfile.MakeDirs(train_dir)
  images, labels = read_cifar10(data_dir=data_dir, image_size=IMAGE_SIZE, batch_size=BATCH_SIZE)
  #print(images,labels)

  #PLACEHOLDER VARIABLES
  keep_prob = tf.placeholder(dtype=tf.float32, shape=())
  learning_rate = tf.placeholder(dtype=tf.float32, shape=())
  regularizer_weight = tf.placeholder(dtype=tf.float32, shape=())
  #Not used --- ^ (currently)

  #MODEL related operations and values
  global_step = tf.Variable(0, trainable=False)
  #MODEL construction
  logits, grad_image, grad_image_placeholder = inference(images)
  loss_op = loss(logits, labels)

  reg_loss = tf.reduce_sum(tf.get_collection(LOSSES_COLLECTION))
  total_loss = loss_op + reg_loss

  accuracy_op = tf.reduce_mean(tf.cast(tf.equal(tf.argmax(logits,1), tf.cast(labels, tf.int64)), tf.float32))
  train_op = train(total_loss, global_step, learning_rate=lr, lr_rate_decay_factor=decay_rate, decay_steps=lr_decay_time * ((NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN //  batch_size) + 1))

  saver = tf.train.Saver(tf.global_variables())

  logits_test = inference_eval_model(images)
  accuracy_test = accuracy_eval_model(logits_test, labels)

  #Summary operation
  summary_op = tf.summary.merge_all()

  acc_summary        = tf.summary.scalar('Training_accuracy_batch', accuracy_op)
  validation_acc_summary = tf.summary.scalar('Validation_accuracy', accuracy_op)
  cross_entropy_loss = tf.summary.scalar('loss_raw', loss_op)
  reg_loss_summary   = tf.summary.scalar('regularization_loss', reg_loss)
  total_loss_summary = tf.summary.scalar('total_loss', total_loss)

  accuracy_batch = tf.placeholder(shape=(None), dtype=tf.float32)
  overfit_estimate = tf.placeholder(shape=(None), dtype=tf.float32)

  accuracy_100 = tf.reduce_mean(accuracy_batch)
  mean_summary = tf.summary.scalar('Training_accuracy_mean', accuracy_100)
  validation_mean_summary = tf.summary.scalar('Validation_accuracy_mean', accuracy_100)

  acc_summary_histogram = tf.summary.histogram('Training_accuracy_histogram', accuracy_batch)
  overfit_summary = tf.summary.scalar('overfit_estimate', overfit_estimate)

  #SESSION Construction
  init = tf.global_variables_initializer()

  config = tf.ConfigProto()
  # config.gpu_options.allow_growth = True
  # config.gpu_options.per_process_gpu_memory_fraction = 0.5
  config.log_device_placement=False

  sess = tf.Session(config=config)
  sess.run(init)
  # input_grad_image = np.zeros((1,32,32,16), dtype=np.float)
  # input_grad_image[0,15,15,:] = 1000.
  # back_image = sess.run(grad_image[0], feed_dict={X_image : 128 * np.ones((1,32,32,3)), regularizer_weight : 0., keep_prob : 1.0, grad_image_placeholder : input_grad_image})
  # print(back_image, np.max(back_image))
  # plt.figure()
  # max_value = np.max(back_image)
  # min_value = np.min(back_image)
  # print(back_image.shape)
  # plt.imshow(back_image[:,:,0], cmap=plt.get_cmap("seismic"), vmin=-1,
  #        vmax=1, interpolation="nearest")
  # plt.show()
  # sys.exit(0)
  tf.train.start_queue_runners(sess=sess)

  #today = date.today()
  current_time = datetime.now()
  # LR_%f, INITIAL_LEARNING_RATE
  # REG_%f, DEFAULT_REG_WEIGHT
  # add details, relating per epoch results (and mean filtered loss etc.)
  train_dir = "cifar10_results/LR_" + str(lr) + "/" + "REG_" + str(reg_weight) + "/" + "KP_" + str(kp) + "/" + current_time.strftime("%B") + "_" + str(current_time.day) + "_" + str(current_time.year) + "-h" + str(current_time.hour) + "m" + str(current_time.minute)
  print("Writing summary data to :  ",train_dir)

  acc_list = []
  valid_acc_list = []

  cm_placeholder = tf.placeholder(shape=(1, None, None, 4), dtype=tf.uint8)
  confusion_summary = tf.summary.image('confusion_matrix', cm_placeholder)

  summary_writer = tf.summary.FileWriter(train_dir, sess.graph)

  batches_per_epoch = NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN // batch_size
  for step in range(MAX_STEPS):
    start_time = time.time()
    _, loss_value, accuracy, acc_str, xentropy_str = sess.run([train_op, loss_op, accuracy_op, acc_summary, cross_entropy_loss])
    summary_writer.add_summary(acc_str, step)
    summary_writer.add_summary(xentropy_str, step)
    duration = time.time() - start_time

    assert not np.isnan(loss_value), 'Model diverged with loss = NaN'
    if step % 10 == 0:
      num_examples_per_step = BATCH_SIZE
      examples_per_sec = num_examples_per_step / duration
      sec_per_batch = float(duration)

      format_str = ('%s: step %d, loss = %.2f, accuracy = %.2f (%.1f examples/sec; %.3f '
                    'sec/batch)')
      print(format_str % (datetime.now(), step, loss_value, (accuracy*100),
                           examples_per_sec, sec_per_batch), flush=True)
    if step != 0 and ((step - 1 ) * batch_size) // NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN != ((step) * batch_size) // NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN:
      print("Starting New Epoch; Epoch %d" % (((step) * BATCH_SIZE) // NUM_EXAMPLES_PER_EPOCH_FOR_TRAIN + 1))
    if step % 100 == 0:
      summary_str = sess.run(summary_op)
      summary_writer.add_summary(summary_str, step)
    if step % 1000 == 0 or (step + 1) == MAX_STEPS:
      checkpoint_path = os.path.join(train_dir, 'model.ckpt')
      saver.save(sess, checkpoint_path, global_step=step)

  return 0


if __name__ == '__main__':
  main()
