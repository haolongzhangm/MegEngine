# -*- coding: utf-8 -*-
# MegEngine is Licensed under the Apache License, Version 2.0 (the "License")
#
# Copyright (c) 2014-2020 Megvii Inc. All rights reserved.
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT ARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
import numpy as np
import pytest

import megengine.core.tensor.raw_tensor
from megengine.core.tensor.core import apply


def elemwise(*args, mode):
    from megengine.core.ops.builtin import Elemwise
    from megengine.core._imperative_rt.imperative import apply_op

    return apply_op(Elemwise(mode=mode).to_c(), args)


def test_basic_interface():
    cf = megengine.core._imperative_rt.OperatorNodeConfig()
    cf.name = "megengine.core"
    cf.dtype = "float32"
    cf.comp_node_arr = ["xpux"]
    print(cf.name)
    print(cf.dtype)
    print(cf.comp_node_arr)
    print(cf.comp_node)
    cf.comp_node_arr = ["xpux", "xpux:1"]
    with pytest.raises(ValueError):
        cf.comp_node


def test_opr_attr():
    from megengine.core.ops.builtin import Elemwise

    assert Elemwise(mode="add") == Elemwise(mode="add")


def test_simple_arith():
    x = np.random.rand(10).astype("float32")
    xx = megengine.core._imperative_rt.put(x)
    (yy,) = elemwise(xx, xx, mode="mul")
    np.testing.assert_allclose(x * x, megengine.core._imperative_rt.get_value(yy))
    megengine.core._imperative_rt.delete(xx)
    megengine.core._imperative_rt.delete(yy)


def test_tensor_on_device():
    device = megengine.core._imperative_rt.CompNode("cpu0:1")
    x = np.random.rand(10).astype("float32")
    xx = megengine.core._imperative_rt.put(x, device=device)
    assert str(megengine.core._imperative_rt.get_device(xx)) == "cpu0:1"
    np.testing.assert_equal(x, megengine.core._imperative_rt.get_value(xx))
    megengine.core._imperative_rt.delete(xx)


def test_raw_tensor():
    from megengine.core.tensor.raw_tensor import as_raw_tensor
    from megengine.core.ops.builtin import Elemwise

    x = np.random.rand(10).astype("float32")
    xx = as_raw_tensor(x)
    (yy,) = apply(Elemwise(mode="mul"), xx, xx)
    np.testing.assert_allclose(x * x, yy.numpy())
    (yy,) = apply(Elemwise(mode="mul"), xx, xx)
    np.testing.assert_allclose(x * x, yy.numpy())
