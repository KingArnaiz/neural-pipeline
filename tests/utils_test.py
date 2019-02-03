import os
import shutil
import sys

from io import StringIO
from contextlib import contextmanager

import torch
from torch import Tensor
import numpy as np
import unittest

from neural_pipeline.utils import FileStructManager, CheckpointsManager, dict_recursive_bypass
from neural_pipeline.utils.file_structure_manager import FolderRegistrable
from tests.common import UseFileStructure

__all__ = ['UtilsTest', 'FileStructManagerTest', 'CheckpointsManagerTests']


@contextmanager
def captured_output():
    new_out, new_err = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err


class UtilsTest(unittest.TestCase):
    def test_dict_recursive_bypass(self):
        d = {'data': np.array([1]), 'target': {'a': np.array([1]), 'b': np.array([1])}}
        d = dict_recursive_bypass(d, lambda v: torch.from_numpy(v))

        self.assertTrue(isinstance(d['data'], Tensor))
        self.assertTrue(isinstance(d['target']['a'], Tensor))
        self.assertTrue(isinstance(d['target']['b'], Tensor))


class FileStructManagerTest(UseFileStructure):
    def test_creation(self):
        if os.path.exists(self.base_dir):
            shutil.rmtree(self.checkpoints_dir, ignore_errors=True)

        try:
            FileStructManager(base_dir=self.base_dir, is_continue=False)
        except FileStructManager.FSMException as err:
            self.fail("Raise error when base directory exists: [{}]".format(err))

        self.assertFalse(os.path.exists(self.base_dir))

        try:
            FileStructManager(base_dir=self.base_dir, is_continue=False)
        except FileStructManager.FSMException as err:
            self.fail("Raise error when base directory exists but empty: [{}]".format(err))

        os.makedirs(os.path.join(self.base_dir, 'new_dir'))
        with self.assertRaises(FileStructManager.FSMException):
            FileStructManager(base_dir=self.base_dir, is_continue=False)
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def test_module_registration(self):
        class TestObj(FolderRegistrable):
            def __init__(self, m: 'FileStructManager', dir: str, name: str):
                super().__init__(m)
                self.dir = dir
                self.name = name

            def get_gir(self) -> str:
                return self.dir

            def get_name(self) -> str:
                return self.name

        fsm = FileStructManager(base_dir=self.base_dir, is_continue=False)
        o = TestObj(fsm, 'test_dir', 'test_name')
        fsm.register_dir(o)

        expected_path = os.path.join(self.base_dir, 'test_dir')
        self.assertFalse(os.path.exists(expected_path))
        self.assertEqual(fsm.get_path(o), expected_path)

        with self.assertRaises(FileStructManager.FSMException):
            fsm.register_dir(TestObj(fsm, 'test_dir', 'another_name'))

        with self.assertRaises(FileStructManager.FSMException):
            fsm.register_dir(TestObj(fsm, 'another_name', 'test_name'))


class CheckpointsManagerTests(UseFileStructure):
    def test_initialisation(self):
        fsm = FileStructManager(base_dir=self.base_dir, is_continue=False)

        try:
            cm = CheckpointsManager(fsm)
        except Exception as err:
            self.fail("Fail init CheckpointsManager; err: ['{}']".format(err))

        with self.assertRaises(FileStructManager.FSMException):
            CheckpointsManager(fsm)

        os.mkdir(os.path.join(fsm.get_path(cm), 'test_dir'))
        with self.assertRaises(FileStructManager.FSMException):
            CheckpointsManager(fsm)

    def test_pack(self):
        fsm = FileStructManager(base_dir=self.base_dir, is_continue=False)
        cm = CheckpointsManager(fsm)
        with self.assertRaises(CheckpointsManager.SMException):
            cm.pack()

        os.mkdir(cm.weights_file())
        os.mkdir(cm.optimizer_state_file())
        with self.assertRaises(CheckpointsManager.SMException):
            cm.pack()

        shutil.rmtree(cm.weights_file())
        shutil.rmtree(cm.optimizer_state_file())

        f = open(cm.weights_file(), 'w')
        f.write('1')
        f.close()
        f = open(cm.optimizer_state_file(), 'w')
        f.write('1')
        f.close()

        try:
            cm.pack()
        except Exception as err:
            self.fail('Exception on packing files: [{}]'.format(err))

        for f in [cm.weights_file(), cm.optimizer_state_file()]:
            if os.path.exists(f) and os.path.isfile(f):
                self.fail("File '{}' doesn't remove after pack".format(f))

        result = os.path.join(fsm.get_path(cm), 'checkpoint.zip')
        self.assertTrue(os.path.exists(result) and os.path.isfile(result))

        f = open(cm.weights_file(), 'w')
        f.write('1')
        f.close()
        f = open(cm.optimizer_state_file(), 'w')
        f.write('1')
        f.close()

        try:
            cm.pack()
            result = os.path.join(fsm.get_path(cm), 'checkpoint.zip.old')
            self.assertTrue(os.path.exists(result) and os.path.isfile(result))
        except Exception as err:
            self.fail('Fail to pack with existing previous state file')

    def test_unpack(self):
        fsm = FileStructManager(base_dir=self.base_dir, is_continue=False)
        cm = CheckpointsManager(fsm)

        f = open(cm.weights_file(), 'w')
        f.write('1')
        f.close()
        f = open(cm.optimizer_state_file(), 'w')
        f.write('2')
        f.close()

        cm.pack()

        try:
            cm.unpack()
        except Exception as err:
            self.fail('Exception on unpacking')

        for i, f in enumerate([cm.weights_file(), cm.optimizer_state_file()]):
            if not (os.path.exists(f) and os.path.isfile(f)):
                self.fail("File '{}' doesn't remove after pack".format(f))
            with open(f, 'r') as file:
                if file.read() != str(i + 1):
                    self.fail("File content corrupted")

    def test_clear_files(self):
        fsm = FileStructManager(base_dir=self.base_dir, is_continue=False)
        cm = CheckpointsManager(fsm)

        f = open(cm.weights_file(), 'w')
        f.close()
        f = open(cm.optimizer_state_file(), 'w')
        f.close()

        cm.clear_files()

        for f in [cm.weights_file(), cm.optimizer_state_file()]:
            if os.path.exists(f) and os.path.isfile(f):
                self.fail("File '{}' doesn't remove after pack".format(f))
