# -*- coding: utf-8 -*-
# MegEngine is Licensed under the Apache License, Version 2.0 (the "License")
#
# Copyright (c) 2014-2020 Megvii Inc. All rights reserved.
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT ARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
from concurrent.futures import Future

import numpy as np

import megengine.functional as F
from megengine.core._imperative_rt import DeviceTensorND
from megengine.core.tensor import megbrain_graph as mgb_graph
from megengine.core.tensor.raw_tensor import as_raw_tensor


def make_dev_tensor(value, dtype=None, device=None):
    return as_raw_tensor(value, dtype=dtype, device=device)._dev_tensor()


def test_io():
    g = mgb_graph.Graph()
    x = make_dev_tensor(np.random.randn(3).astype("float32"), device="xpux")
    vx, _ = mgb_graph.input_callback(
        lambda: x, device=x.comp_node, dtype=x.dtype, graph=g
    )
    y = Future()
    v = mgb_graph.output_callback(y.set_result, vx)
    f = g.compile(v)
    f()

    np.testing.assert_equal(x.numpy(), y.result().numpy())


def test_io2():
    g = mgb_graph.Graph()
    g.options.async_exec_level = 0b100
    dtype, device = "float32", "xpux"
    px = mgb_graph.InputNode(device=device, dtype=dtype, graph=g)
    py = mgb_graph.OutputNode(px.outputs[0])
    f = g.compile(py.outputs[0])

    for _ in range(3):
        f.execute()
        x = make_dev_tensor(np.random.randn(10).astype(dtype), device=device)
        px.set_value(x)
        y = py.get_value()
        np.testing.assert_equal(x.numpy(), y.numpy())
        f.wait()


def test_attr_output():
    g = mgb_graph.Graph()
    g.options.async_exec_level = 0b100
    dtype, device = "float32", "xpux"
    px = mgb_graph.InputNode(device=device, dtype=dtype, graph=g)
    py = mgb_graph.AttrOutputNode(px.outputs[0])
    f = g.compile(py.outputs[0])

    for shape in [(2,), (3,), (5,)]:
        f.execute()
        x = make_dev_tensor(np.random.randn(*shape).astype(dtype), device=device)
        px.set_value(x)
        ay = py.get_value()
        assert ay.shape == shape
        assert ay.dtype == np.dtype(dtype)
        assert ay.device == device
        f.wait()


def test_op():
    g = mgb_graph.Graph()
    x = make_dev_tensor(np.random.randn(10).astype("float32"), device="xpux")
    v, _ = mgb_graph.input_callback(
        lambda: x, device=x.comp_node, dtype=x.dtype, graph=g
    )
    v = F.neg(v)
    y = Future()
    v = mgb_graph.output_callback(y.set_result, v)
    f = g.compile(v)
    f()

    np.testing.assert_equal(x.numpy(), -y.result().numpy())
