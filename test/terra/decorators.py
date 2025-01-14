# -*- coding: utf-8 -*-

# This code is part of Qiskit.
#
# (C) Copyright IBM 2017, 2020.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Decorator for using with Qiskit Aer unit tests."""

import multiprocessing
import unittest

from qiskit import QuantumCircuit, execute
from qiskit.utils import wrap_method

from qiskit_aer import AerProvider, AerSimulator

from typing import Union, Callable, Type, Iterable


def is_method_available(backend, method):
    """Check if input method is available for the qasm simulator."""
    if isinstance(backend, str):
        backend = AerProvider().get_backend(backend)
    avail = backend.available_methods()
    if method in avail:
        return True
    else:
        return False


def requires_method(backend, method):
    """Decorator that skips test if a simulation method is unavailable.

    Args:
        backend (str or AerBackend): backend to check method for.
        method (str): the method string

    Returns:
        decorator: the decorator for testing input method.
    """
    reason = 'method "{}" is unavailable, skipping test'.format(method)
    skip = not is_method_available(backend, method)
    return unittest.skipIf(skip, reason)


def requires_omp(test_item):
    """Decorator that skips test if OpenMP is not available.

    Args:
        test_item (callable): function or class to be decorated.

    Returns:
        callable: the decorated function.
    """
    # Run dummy circuit to check OpenMP status
    result = AerSimulator().run(QuantumCircuit(1)).result()
    omp_enabled = result.metadata.get("omp_enabled", False)
    skip = not omp_enabled
    reason = "OpenMP not available, skipping test"
    return unittest.skipIf(skip, reason)(test_item)


def requires_multiprocessing(test_item):
    """Decorator that skips test if run on single-core CPU.

    Args:
        test_item (callable): function or class to be decorated.

    Returns:
        callable: the decorated function.
    """
    skip = multiprocessing.cpu_count() <= 1
    reason = "Multicore CPU not available, skipping test"
    return unittest.skipIf(skip, reason)(test_item)


def deprecated(method):
    """Decorator that is for deprecated methods.

    Args:
        method (callable): a deprecated method.

    Returns:
        callable: the decorated method.
    """

    def _deprecated_method(self, *args, **kwargs):
        with self.assertWarns(DeprecationWarning):
            method(self, *args, **kwargs)

    return _deprecated_method


def enforce_subclasses_call(
    methods: Union[str, Iterable[str]], attr: str = "_enforce_subclasses_call_cache"
) -> Callable[[Type], Type]:
    """Class decorator which enforces that if any subclasses define on of the ``methods``, they must
    call ``super().<method>()`` or face a ``ValueError`` at runtime.

    This is unlikely to be useful for concrete test classes, who are not normally subclassed.  It
    should not be used on user-facing code, because it prevents subclasses from being free to
    override parent-class behavior, even when the parent-class behavior is not needed.

    This adds behavior to the ``__init__`` and ``__init_subclass__`` methods of the class, in
    addition to the named methods of this class and all subclasses.  The checks could be averted in
    grandchildren if a child class overrides ``__init_subclass__`` without up-calling the decorated
    class's method, though this would typically break inheritance principles.

    Arguments:
        methods:
            Names of the methods to add the enforcement to.  These do not necessarily need to be
            defined in the class body, provided they are somewhere in the method-resolution tree.

        attr:
            The attribute which will be added to all instances of this class and subclasses, in
            order to manage the call enforcement.  This can be changed to avoid clashes.

    Returns:
        A decorator, which returns its input class with the class with the relevant methods modified
        to include checks, and injection code in the ``__init_subclass__`` method.
    """

    methods = {methods} if isinstance(methods, str) else set(methods)

    def initialize_call_memory(self, *_args, **_kwargs):
        """Add the extra attribute used for tracking the method calls."""
        setattr(self, attr, set())

    def save_call_status(name):
        """Decorator, whose return saves the fact that the top-level method call occurred."""

        def out(self, *_args, **_kwargs):
            getattr(self, attr).add(name)

        return out

    def clear_call_status(name):
        """Decorator, whose return clears the call status of the method ``name``.  This prepares the
        call tracking for the child class's method call."""

        def out(self, *_args, **_kwargs):
            getattr(self, attr).discard(name)

        return out

    def enforce_call_occurred(name):
        """Decorator, whose return checks that the top-level method call occurred, and raises
        ``ValueError`` if not.  Concretely, this is an assertion that ``save_call_status`` ran."""

        def out(self, *_args, **_kwargs):
            cache = getattr(self, attr)
            if name not in cache:
                classname = self.__name__ if isinstance(self, type) else type(self).__name__
                raise ValueError(
                    f"Parent '{name}' method was not called by '{classname}.{name}'."
                    f" Ensure you have put in calls to 'super().{name}()'."
                )

        return out

    def wrap_subclass_methods(cls):
        """Wrap all the ``methods`` of ``cls`` with the call-tracking assertions that the top-level
        versions of the methods were called (likely via ``super()``)."""
        # Only wrap methods who are directly defined in this class; if we're resolving to a method
        # higher up the food chain, then it will already have been wrapped.
        for name in set(cls.__dict__) & methods:
            wrap_method(
                cls,
                name,
                before=clear_call_status(name),
                after=enforce_call_occurred(name),
            )

    def decorator(cls):
        # Add a class-level memory on, so class methods will work as well.  Instances will override
        # this on instantiation, to keep the "namespace" of class- and instance-methods separate.
        initialize_call_memory(cls)
        # Do the extra bits after the main body of __init__ so we can check we're not overwriting
        # anything, and after __init_subclass__ in case the decorated class wants to influence the
        # creation of the subclass's methods before we get to them.
        wrap_method(cls, "__init__", after=initialize_call_memory)
        for name in methods:
            wrap_method(cls, name, before=save_call_status(name))
        wrap_method(cls, "__init_subclass__", after=wrap_subclass_methods)
        return cls

    return decorator
