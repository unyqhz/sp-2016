#!/usr/bin/env python
"""
Train a per-subject model for:
https://www.kaggle.com/c/melbourne-university-seizure-prediction

Usage:
    ./model.py -e 16 -w </path/to/data> -r 0 -z 64 -elec <electrode index>
"""

import os
import glob
import sys
import numpy as np
from neon.util.argparser import NeonArgparser
from neon.initializers import Gaussian, GlorotUniform
from neon.layers import Conv, Pooling, GeneralizedCost, Affine
from neon.layers import DeepBiRNN, RecurrentMean
from neon.optimizers import Adagrad
from neon.transforms import Rectlin, Softmax, CrossEntropyBinary
from neon.models import Model
from neon.data import DataLoader, AudioParams
from neon.callbacks.callbacks import Callbacks
from sklearn import metrics
from indexer import Indexer


def run(tain, test):
    gauss = Gaussian(scale=0.01)
    glorot = GlorotUniform()
    tiny = dict(str_h=1, str_w=1)
    small = dict(str_h=1, str_w=2)
    big = dict(str_h=1, str_w=4)
    common = dict(batch_norm=True, activation=Rectlin())
    layers = [Conv((3, 5, 64), init=gauss, activation=Rectlin(), strides=big),
              Pooling(2, strides=2),
              Conv((3, 3, 128), init=gauss, strides=small, **common),
              Pooling(2, strides=2),
              Conv((3, 3, 256), init=gauss, strides=small, **common),
              Conv((2, 2, 512), init=gauss, strides=tiny, **common),
              DeepBiRNN(128, init=glorot, reset_cells=True, depth=3, **common),
              RecurrentMean(),
              Affine(nout=2, init=gauss, activation=Softmax())]

    model = Model(layers=layers)
    opt = Adagrad(learning_rate=0.001)
    callbacks = Callbacks(model, eval_set=test, **args.callback_args)
    cost = GeneralizedCost(costfunc=CrossEntropyBinary())

    model.fit(tain, optimizer=opt, num_epochs=args.epochs, cost=cost, callbacks=callbacks)
    return model


parser = NeonArgparser(__doc__)
parser.add_argument('-elec', '--electrode', default=0, help='electrode index')
parser.add_argument('-skip', '--skip_test', action="store_true",
                    help="skip testing (validation mode)")
args = parser.parse_args()
pattern = '*.' + str(args.electrode) + '.wav'
data_dir = args.data_dir
if data_dir[-1] != '/':
    data_dir += '/'
subj = int(data_dir[-2])
assert subj in [1, 2, 3]
indexer = Indexer(data_dir, [args.electrode])
tain_idx, test_idx = indexer.run(data_dir, pattern)

fs = 400
cd = 240000 * 1000 / fs
common_params = dict(sampling_freq=fs, clip_duration=cd, frame_duration=512)
tain_params = AudioParams(random_scale_percent=5.0, **common_params)
test_params = AudioParams(**common_params)
common = dict(target_size=1, nclasses=2)
tain = DataLoader(set_name='tain', media_params=tain_params, index_file=tain_idx,
                  repo_dir=data_dir, shuffle=True, **common)
test = DataLoader(set_name='eval', media_params=test_params, index_file=test_idx,
                  repo_dir=data_dir, **common)
model = run(tain, test)
preds = model.get_outputs(test)[:, 1]
labels = np.loadtxt(test_idx, delimiter=',', skiprows=1, usecols=[1])
print('Eval AUC for subject %d: %.4f' % (subj, metrics.roc_auc_score(labels, preds)))

eval_preds = os.path.join(data_dir, 'eval.' + str(args.electrode) + '.npy')
np.save(eval_preds, preds)
if args.skip_test is True:
    sys.exit(0)

test_dir = data_dir.replace('train', 'test')
tain_idx, test_idx = indexer.run(data_dir, pattern, testing=True)
tain = DataLoader(set_name='full', media_params=tain_params, index_file=tain_idx,
                  repo_dir=data_dir, shuffle=True, **common)
test = DataLoader(set_name='test', media_params=test_params, index_file=test_idx,
                  repo_dir=test_dir, **common)
model = run(tain, test)
test_preds = model.get_outputs(test)[:, 1]
test_file = 'test.' + str(subj) + '.' + str(args.electrode) + '.npy'
np.save(test_file, test_preds)