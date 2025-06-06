# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""Regression tests for the units package."""

import itertools
import operator
import pickle
from contextlib import nullcontext
from fractions import Fraction

import numpy as np
import pytest
from numpy.testing import assert_allclose

from astropy import constants as c
from astropy import units as u
from astropy.units import utils
from astropy.units.required_by_vounit import GsolLum, ksolMass, nsolRad
from astropy.utils.compat.optional_deps import HAS_ARRAY_API_STRICT, HAS_DASK
from astropy.utils.exceptions import AstropyDeprecationWarning

FLOAT_EPS = np.finfo(float).eps


def test_initialisation():
    assert u.Unit(u.m) is u.m

    ten_meter = u.Unit(10.0 * u.m)
    assert ten_meter == u.CompositeUnit(10.0, [u.m], [1])
    assert u.Unit(ten_meter) is ten_meter

    assert u.Unit(10.0 * ten_meter) == u.CompositeUnit(100.0, [u.m], [1])

    foo = u.Unit("foo", (10.0 * ten_meter) ** 2, namespace=locals())
    assert foo == u.CompositeUnit(10000.0, [u.m], [2])

    assert u.Unit("m") == u.m
    assert u.Unit("") == u.dimensionless_unscaled
    assert u.one == u.dimensionless_unscaled
    assert u.Unit("10 m") == ten_meter

    assert u.Unit() == u.dimensionless_unscaled


@pytest.mark.parametrize(
    "input_,power_value,power_type",
    [
        pytest.param(2.0, 2, int, id="integer_as_float"),
        pytest.param(Fraction(2, 1), 2, int, id="numerator_is_one"),
        pytest.param(Fraction(1, 2), 0.5, float, id=r"numerator_is_power_of_two"),
        pytest.param(np.float64(117 / 1123), 117 / 1123, float, id="float-like"),
        pytest.param(np.int64(3), 3, int, id="int-like"),
    ],
)
def test_power_types(input_, power_value, power_type):
    # Regression test for #16779 - power could sometimes be a numpy number
    powers = (u.m**input_).powers
    assert list(map(type, powers)) == [power_type]
    assert_allclose(powers, power_value)


def test_raise_to_power():
    x = u.m ** Fraction(1, 3)
    assert isinstance(x.powers[0], Fraction)

    x = u.m ** Fraction(1, 2)
    assert isinstance(x.powers[0], float)

    # Test the automatic conversion to a fraction
    x = u.m ** (1.0 / 3.0)
    assert isinstance(x.powers[0], Fraction)

    # Test power remains integer if possible
    x = (u.m**2) ** 0.5
    assert isinstance(x.powers[0], int)

    x = (u.m**-6) ** (1 / 3)
    assert isinstance(x.powers[0], int)


def test_invalid_compare():
    assert not (u.m == u.s)


@pytest.mark.parametrize(
    "original,expectation",
    [
        pytest.param(1, 3600.0, id="small_int"),
        pytest.param(2.0, 7200.0, id="small_float"),
        pytest.param(10**25, 3.6e28, id="large_int"),
        pytest.param(3e25, 1.08e29, id="large_float"),
    ],
)
def test_convert(original, expectation):
    result = u.h.get_converter(u.s)(original)
    assert_allclose(result, expectation, rtol=1e-15, atol=0)
    assert type(result) is float


def test_convert_roundtrip():
    c1 = u.cm.get_converter(u.m)
    c2 = u.m.get_converter(u.cm)
    assert_allclose(c1(c2(10.0)), c2(c1(10.0)), rtol=1e-15, atol=0)


def test_convert_roundtrip_with_equivalency():
    c1 = u.arcsec.get_converter(u.pc, u.parallax())
    c2 = u.pc.get_converter(u.arcsec, u.parallax())
    assert_allclose(c1(c2(10.0)), c2(c1(10.0)), rtol=1e-15, atol=0)


def test_convert_fail():
    with pytest.raises(u.UnitsError):
        u.cm.to(u.s, 1)
    with pytest.raises(u.UnitsError):
        (u.cm / u.s).to(u.m, 1)


def test_composite():
    assert (u.cm / u.s * u.h).get_converter(u.m)(1) == 36
    assert u.cm * u.cm == u.cm**2

    assert u.cm * u.cm * u.cm == u.cm**3

    assert u.Hz.to(1000 * u.Hz, 1) == 0.001


def test_str():
    assert str(u.cm) == "cm"


def test_repr():
    assert repr(u.cm) == 'Unit("cm")'


def test_represents():
    assert u.m.represents is u.m
    assert u.km.represents.scale == 1000.0
    assert u.km.represents.bases == [u.m]
    assert u.Ry.scale == 1.0 and u.Ry.bases == [u.Ry]
    assert_allclose(u.Ry.represents.scale, 13.605692518464949)
    assert u.Ry.represents.bases == [u.eV]
    bla = u.def_unit("bla", namespace=locals())
    assert bla.represents is bla
    blabla = u.def_unit("blabla", 10 * u.hr, namespace=locals())
    assert blabla.represents.scale == 10.0
    assert blabla.represents.bases == [u.hr]
    assert blabla.decompose().scale == 10 * 3600
    assert blabla.decompose().bases == [u.s]


@pytest.mark.parametrize("func", [u.Unit, u.def_unit])
@pytest.mark.parametrize(
    "represents, match_",
    [("not_a_unit", "did not parse"), ([5, 6] * u.hr, "more than one element")],
)
def test_represents_errors(func, represents, match_):
    with pytest.raises(ValueError, match=match_):
        func("new_unit", represents)


def test_units_conversion():
    assert_allclose(u.kpc.to(u.Mpc), 0.001)
    assert_allclose(u.Mpc.to(u.kpc), 1000)
    assert_allclose(u.yr.to(u.Myr), 1.0e-6)
    assert_allclose(u.AU.to(u.pc), 4.84813681e-6)
    assert_allclose(u.cycle.to(u.rad), 6.283185307179586)
    assert_allclose(u.spat.to(u.sr), 12.56637061435917)


def test_decompose():
    assert u.Ry == u.Ry.decompose()


def test_dimensionless_to_si():
    """
    Issue #1150: Test for conversion of dimensionless quantities
                 to the SI system
    """

    testunit = (1.0 * u.kpc) / (1.0 * u.Mpc)

    assert testunit.unit.physical_type == "dimensionless"
    assert_allclose(testunit.si, 0.001)


def test_dimensionless_to_cgs():
    """
    Issue #1150: Test for conversion of dimensionless quantities
                 to the CGS system
    """

    testunit = (1.0 * u.m) / (1.0 * u.km)

    assert testunit.unit.physical_type == "dimensionless"
    assert_allclose(testunit.cgs, 0.001)


def test_unknown_unit():
    with pytest.warns(u.UnitsWarning, match="FOO"):
        u.Unit("FOO", parse_strict="warn")


def test_multiple_solidus():
    with pytest.warns(
        u.UnitsWarning,
        match="'m/s/kg' contains multiple slashes, which is discouraged",
    ):
        assert u.Unit("m/s/kg").to_string() == "m / (kg s)"

    with pytest.raises(ValueError, match="contains multiple slashes"):
        u.Unit("m/s/kg", format="vounit")

    # Regression test for #9000: solidi in exponents do not count towards this.
    x = u.Unit("kg(3/10) * m(5/2) / s", format="vounit")
    assert x.to_string() == "m(5/2) kg(3/10) / s"


def test_unknown_unit3():
    unit = u.Unit("FOO", parse_strict="silent")
    assert isinstance(unit, u.UnrecognizedUnit)
    assert unit.name == "FOO"

    unit2 = u.Unit("FOO", parse_strict="silent")
    assert unit == unit2
    assert unit.is_equivalent(unit2)

    unit3 = u.Unit("BAR", parse_strict="silent")
    assert unit != unit3
    assert not unit.is_equivalent(unit3)

    # Also test basic (in)equalities.
    assert unit == "FOO"
    assert unit != u.m
    # next two from gh-7603.
    assert unit != None
    assert unit not in (None, u.m)

    with pytest.raises(ValueError):
        unit.get_converter(unit3)

    _ = unit.to_string("latex")
    _ = unit2.to_string("cgs")

    with pytest.raises(ValueError):
        u.Unit("BAR", parse_strict="strict")

    with pytest.raises(TypeError):
        u.Unit(None)


@pytest.mark.parametrize(
    "parse_strict,expectation",
    [
        pytest.param("silent", nullcontext(), id="silent"),
        pytest.param(
            "warn",
            pytest.warns(u.UnitParserWarning, match=r"meant to be a multiplication,"),
            id="warn",
        ),
        pytest.param(
            "raise",
            pytest.raises(ValueError, match=r"was meant to be a multiplication, "),
            id="raise",
        ),
        pytest.param(
            "error",
            pytest.raises(
                ValueError,
                match=r"^'parse_strict' must be 'warn', 'raise' or 'silent'$",
            ),
            id="invalid",
        ),
    ],
)
def test_parse_strict_noncritical_error(parse_strict, expectation):
    with expectation:
        assert u.Unit("m(s)", format="ogip", parse_strict=parse_strict) == u.m * u.s


def test_parse_strict_noncritical_error_default():
    with pytest.raises(
        ValueError,
        match=(
            r"^if 'm\(s\)' was meant to be a multiplication, it should have been "
            r"written as 'm \(s\)'\.\n"
            "If you cannot change the unit string then try specifying the "
            r"'parse_strict' argument\.$"
        ),
    ):
        assert u.Unit("m(s)", format="ogip")


def test_invalid_scale():
    with pytest.raises(TypeError):
        ["a", "b", "c"] * u.m


@pytest.mark.parametrize("op", [operator.truediv, operator.lshift, operator.mul])
def test_invalid_array_op(op):
    # see https://github.com/astropy/astropy/issues/12836
    with pytest.raises(
        TypeError, match="The value must be a valid Python or Numpy numeric type"
    ):
        op(np.array(["cat"]), u.one)


def test_cds_power():
    unit = u.Unit("10+22/cm2", format="cds", parse_strict="silent")
    assert unit.scale == 1e22


def test_register():
    foo = u.def_unit("foo", u.m**3, namespace=locals())
    assert "foo" in locals()
    with u.add_enabled_units(foo):
        assert "foo" in u.get_current_unit_registry().registry
    assert "foo" not in u.get_current_unit_registry().registry


def test_in_units_deprecation():
    with pytest.warns(AstropyDeprecationWarning, match=r"Use to\(\) instead\.$"):
        assert (u.m / u.s).in_units(u.cm / u.s) == 100


def test_null_unit():
    assert (u.m / u.m) == u.Unit(1)


def test_unrecognized_equivalency():
    assert u.m.is_equivalent("foo") is False
    assert u.m.is_equivalent("pc") is True


def test_convertible_exception():
    with pytest.raises(u.UnitsError, match=r"length.+ are not convertible"):
        u.AA.to(u.h * u.s**2)


def test_convertible_exception2():
    with pytest.raises(u.UnitsError, match=r"length. and .+time.+ are not convertible"):
        u.m.to(u.s)


def test_invalid_type():
    class A:
        pass

    with pytest.raises(TypeError):
        u.Unit(A())


def test_steradian():
    """
    Issue #599
    """
    assert u.sr.is_equivalent(u.rad * u.rad)

    results = u.sr.compose(units=u.cgs.bases)
    assert results[0].bases[0] is u.rad

    results = u.sr.compose(units=u.cgs.__dict__)
    assert results[0].bases[0] is u.sr


def test_decompose_bases():
    """
    From issue #576
    """

    from astropy.constants import e
    from astropy.units import cgs

    d = e.esu.unit.decompose(bases=cgs.bases)
    assert d._bases == [u.cm, u.g, u.s]
    assert d._powers == [Fraction(3, 2), 0.5, -1]
    assert d._scale == 1.0


def test_complex_compose():
    complex = u.cd * u.sr * u.Wb
    composed = complex.compose()

    assert set(composed[0]._bases) == {u.lm, u.Wb}


def test_equiv_compose():
    composed = u.m.compose(equivalencies=u.spectral())
    assert any([u.Hz] == x.bases for x in composed)


def test_empty_compose():
    with pytest.raises(u.UnitsError):
        u.m.compose(units=[])


# We use a set to make sure we don't have any duplicates.
COMPOSE_ROUNDTRIP = set()
for val in u.__dict__.values():
    if isinstance(val, u.UnitBase) and not isinstance(val, u.PrefixUnit):
        COMPOSE_ROUNDTRIP.add(val)


@pytest.mark.parametrize("unit", sorted(COMPOSE_ROUNDTRIP, key=str), ids=repr)
def test_compose_roundtrip(unit):
    composed_list = unit.decompose().compose()
    found = False
    for composed in composed_list:
        if len(composed.bases):
            if composed.bases[0] is unit:
                found = True
                break
        elif len(unit.bases) == 0:
            found = True
            break
    assert found


# We use a set to make sure we don't have any duplicates.
COMPOSE_CGS_TO_SI = set()
for val in u.cgs.__dict__.values():
    # Can't decompose Celsius
    if (
        isinstance(val, u.UnitBase)
        and not isinstance(val, u.PrefixUnit)
        and val != u.cgs.deg_C
    ):
        COMPOSE_CGS_TO_SI.add(val)


@pytest.mark.parametrize("unit", sorted(COMPOSE_CGS_TO_SI, key=str), ids=str)
def test_compose_cgs_to_si(unit):
    si = unit.to_system(u.si)
    assert [x.is_equivalent(unit) for x in si]
    assert si[0] == unit.si
    assert np.isclose(si[0].scale, unit.decompose(bases=u.si.bases).scale)


# We use a set to make sure we don't have any duplicates.
COMPOSE_SI_TO_CGS = set()
for val in u.si.__dict__.values():
    # Can't decompose Celsius
    if (
        isinstance(val, u.UnitBase)
        and not isinstance(val, u.PrefixUnit)
        and val != u.si.deg_C
    ):
        COMPOSE_SI_TO_CGS.add(val)


@pytest.mark.parametrize("unit", sorted(COMPOSE_SI_TO_CGS, key=str), ids=str)
def test_compose_si_to_cgs(unit):
    # Can't convert things with Ampere to CGS without more context
    try:
        cgs = unit.to_system(u.cgs)
    except u.UnitsError:
        if u.A in unit.decompose().bases:
            pass
        else:
            raise
    else:
        assert [x.is_equivalent(unit) for x in cgs]
        assert cgs[0] == unit.cgs
        assert np.isclose(cgs[0].scale, unit.decompose(bases=u.cgs.bases).scale)


def test_to_si():
    """Check units that are not official derived units.

    Should not appear on its own or as part of a composite unit.
    """
    # TODO: extend to all units not listed in Tables 1--6 of
    # https://physics.nist.gov/cuu/Units/units.html
    # See gh-10585.
    # This was always the case
    assert u.bar.si is not u.bar
    # But this used to fail.
    assert u.bar not in (u.kg / (u.s**2 * u.sr * u.nm)).si._bases


def test_to_cgs():
    assert u.Pa.to_system(u.cgs)[0].bases[0] is u.Ba
    assert u.Pa.to_system(u.cgs)[0].scale == 10.0


@pytest.mark.parametrize(
    "unit, system, expected_bases",
    [
        (u.Pa, "si", [u.Pa]),
        (u.sr, "si", [u.rad]),
        (u.Gal, "si", [u.m, u.s]),
        (u.Gal, "cgs", [u.cm, u.s]),
    ],
)
def test_to_system_best_unit(unit, system, expected_bases):
    in_system = getattr(unit, system)
    assert in_system.bases == expected_bases


def test_decompose_to_cgs():
    from astropy.units import cgs

    assert u.m.decompose(bases=cgs.bases)._bases[0] is cgs.cm


def test_compose_issue_579():
    unit = u.kg * u.s**2 / u.m

    result = unit.compose(units=[u.N, u.s, u.m])

    assert len(result) == 1
    assert result[0]._bases == [u.s, u.N, u.m]
    assert result[0]._powers == [4, 1, -2]


def test_compose_prefix_unit():
    x = u.m.compose(units=(u.m,))
    assert x[0].bases[0] is u.m
    assert x[0].scale == 1.0
    x = u.m.compose(units=[u.km], include_prefix_units=True)
    assert x[0].bases[0] is u.km
    assert x[0].scale == 0.001
    x = u.m.compose(units=[u.km])
    assert x[0].bases[0] is u.km
    assert x[0].scale == 0.001

    x = (u.km / u.s).compose(units=(u.pc, u.Myr))
    assert x[0].bases == [u.pc, u.Myr]
    assert_allclose(x[0].scale, 1.0227121650537077)

    with pytest.raises(u.UnitsError):
        (u.km / u.s).compose(units=(u.pc, u.Myr), include_prefix_units=False)


def test_self_compose():
    unit = u.kg * u.s

    assert len(unit.compose(units=[u.g, u.s])) == 1


def test_compose_failed():
    unit = u.kg
    with pytest.raises(u.UnitsError):
        unit.compose(units=[u.N])


def test_compose_fractional_powers():
    # Warning: with a complicated unit, this test becomes very slow;
    # e.g., x = (u.kg / u.s ** 3 * u.au ** 2.5 / u.yr ** 0.5 / u.sr ** 2)
    # takes 3 s
    x = u.m**0.5 / u.yr**1.5

    factored = x.compose()

    for unit in factored:
        assert x.decompose() == unit.decompose()

    factored = x.compose(units=u.cgs)

    for unit in factored:
        assert x.decompose() == unit.decompose()

    factored = x.compose(units=u.si)

    for unit in factored:
        assert x.decompose() == unit.decompose()


def test_compose_best_unit_first():
    results = u.l.compose()
    assert len(results[0].bases) == 1
    assert results[0].bases[0] is u.l

    results = (u.s**-1).compose()
    assert results[0].bases[0] in (u.Hz, u.Bq)

    results = (u.Ry.decompose()).compose()
    assert results[0].bases[0] is u.Ry


def test_compose_no_duplicates():
    new = u.kg / u.s**3 * u.au**2.5 / u.yr**0.5 / u.sr**2
    composed = new.compose(units=u.cgs.bases)
    assert len(composed) == 1


@pytest.mark.parametrize(
    "dtype", tuple(map("".join, itertools.product("<>", "if", "48")))
)
def test_endian_independence(dtype):
    """
    Regression test for #744

    A logic issue in the units code meant that big endian arrays could not be
    converted because the dtype is '>f4', not 'float32', and the code was
    looking for the strings 'float' or 'int'.
    """
    x = np.array([1, 2, 3], dtype=dtype)
    assert u.m.to(u.cm, x).tolist() == [100.0, 200.0, 300.0]


def test_radian_base():
    """
    Issue #863
    """
    assert (1 * u.degree).si.unit == u.rad


def test_no_as():
    # We don't define 'as', since it is a keyword, but we
    # do want to define the long form (`attosecond`).
    assert not hasattr(u, "as")
    assert hasattr(u, "attosecond")


def test_no_duplicates_in_names():
    # Regression test for #5036
    assert u.ct.names == ["ct", "count"]
    assert u.ct.short_names == ["ct", "count"]
    assert u.ct.long_names == ["count"]
    assert set(u.ph.names) == set(u.ph.short_names) | set(u.ph.long_names)


def test_pickling():
    p = pickle.dumps(u.m)
    other = pickle.loads(p)

    assert other is u.m

    new_unit = u.IrreducibleUnit(["foo"], format={"unicode": "bar"})
    # This is local, so the unit should not be registered.
    assert "foo" not in u.get_current_unit_registry().registry

    # Test pickling of this unregistered unit.
    p = pickle.dumps(new_unit)
    new_unit_copy = pickle.loads(p)
    assert new_unit_copy is not new_unit
    assert new_unit_copy.names == ["foo"]
    assert new_unit_copy.to_string("unicode") == "bar"
    # It should still not be registered.
    assert "foo" not in u.get_current_unit_registry().registry

    # Now try the same with a registered unit.
    with u.add_enabled_units([new_unit]):
        p = pickle.dumps(new_unit)
        assert "foo" in u.get_current_unit_registry().registry
        new_unit_copy = pickle.loads(p)
        assert new_unit_copy is new_unit

    # Check that a registered unit can be loaded and that it gets re-enabled.
    with u.add_enabled_units([]):
        assert "foo" not in u.get_current_unit_registry().registry
        new_unit_copy = pickle.loads(p)
        assert new_unit_copy is not new_unit
        assert new_unit_copy.names == ["foo"]
        assert new_unit_copy.to_string("unicode") == "bar"
        assert "foo" in u.get_current_unit_registry().registry

    # And just to be sure, that it gets removed outside of the context.
    assert "foo" not in u.get_current_unit_registry().registry


def test_pickle_between_sessions():
    """We cannot really test between sessions easily, so fake it.

    This test can be changed if the pickle protocol or the code
    changes enough that it no longer works.

    """
    hash_m = hash(u.m)
    unit = pickle.loads(
        b"\x80\x04\x95\xd6\x00\x00\x00\x00\x00\x00\x00\x8c\x12"
        b"astropy.units.core\x94\x8c\x1a_recreate_irreducible_unit"
        b"\x94\x93\x94h\x00\x8c\x0fIrreducibleUnit\x94\x93\x94]\x94"
        b"(\x8c\x01m\x94\x8c\x05meter\x94e\x88\x87\x94R\x94}\x94(\x8c\x06"
        b"_names\x94]\x94(h\x06h\x07e\x8c\x0c_short_names"
        b"\x94]\x94h\x06a\x8c\x0b_long_names\x94]\x94h\x07a\x8c\x07"
        b"_format\x94}\x94\x8c\x07__doc__\x94\x8c "
        b"meter: base unit of length in SI\x94ub."
    )
    assert unit is u.m
    assert hash(u.m) == hash_m


@pytest.mark.parametrize(
    "unit",
    [u.IrreducibleUnit(["foo"], format={"baz": "bar"}), u.Unit("m_per_s", u.m / u.s)],
)
def test_pickle_does_not_keep_memoized_hash(unit):
    """
    Tests private attribute since the problem with _hash being pickled
    and restored only appeared if the unpickling was done in another
    session, for which the hash no longer was valid, and it is difficult
    to mimic separate sessions in a simple test. See gh-11872.
    """
    unit_hash = hash(unit)
    assert "_hash" in vars(unit)
    unit_copy = pickle.loads(pickle.dumps(unit))
    # unit is not registered so we get a copy.
    assert unit_copy is not unit
    assert "_hash" not in vars(unit_copy)
    assert hash(unit_copy) == unit_hash
    with u.add_enabled_units([unit]):
        # unit is registered, so we get a reference.
        unit_ref = pickle.loads(pickle.dumps(unit))
        if isinstance(unit, u.IrreducibleUnit):
            assert unit_ref is unit
        else:
            assert unit_ref is not unit
        # pickle.load used to override the hash, although in this case
        # it would be the same anyway, so not clear this tests much.
        assert hash(unit) == unit_hash


def test_pickle_unrecognized_unit():
    """
    Issue #2047
    """
    a = u.Unit("asdf", parse_strict="silent")
    assert isinstance(pickle.loads(pickle.dumps(a)), u.UnrecognizedUnit)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("h", id="simple_conflict"),
        pytest.param("ʰ", id="NFKC_normalization"),
    ],
)
def test_duplicate_define(name):
    namespace = {"h": u.h}
    with pytest.raises(
        ValueError,
        match=(
            "^Object with NFKC normalized name 'h' already exists in given namespace "
            r'\(Unit\("h"\)\)\.$'
        ),
    ):
        u.def_unit(name, u.hourangle, namespace=namespace)


def test_all_units():
    from astropy.units.core import get_current_unit_registry

    registry = get_current_unit_registry()
    assert len(registry.all_units) > len(registry.non_prefix_units)


def test_repr_latex():
    assert u.m._repr_latex_() == u.m.to_string("latex")


def test_operations_with_strings():
    with pytest.warns(
        AstropyDeprecationWarning,
        match=(
            "^divisions involving a unit and a 'str' instance are deprecated since "
            r"v7\.1\. Convert '5s' to a unit explicitly\.$"
        ),
    ):
        assert u.m / "5s" == (u.m / (5.0 * u.s))

    with pytest.warns(
        AstropyDeprecationWarning,
        match=(
            "^products involving a unit and a 'str' instance are deprecated since "
            r"v7\.1\. Convert '5s' to a unit explicitly\.$"
        ),
    ):
        assert u.m * "5s" == (5.0 * u.m * u.s)


def test_comparison():
    assert u.m > u.cm
    assert u.m >= u.cm
    assert u.cm < u.m
    assert u.cm <= u.m

    with pytest.raises(u.UnitsError):
        u.m > u.kg  # noqa: B015


def test_compose_into_arbitrary_units():
    # Issue #1438
    from astropy.constants import G

    G_decomposed = G.decompose([u.kg, u.km, u.Unit("100 s")])
    assert_allclose(G_decomposed.unit.scale, 1e-4)
    assert G_decomposed == G


def test_unit_multiplication_with_string():
    with pytest.warns(
        AstropyDeprecationWarning,
        match=(
            "^products involving a unit and a 'str' instance are deprecated since "
            r"v7\.1\. Convert 'kg' to a unit explicitly\.$"
        ),
    ):
        assert "kg" * u.cm == u.kg * u.cm
    with pytest.warns(AstropyDeprecationWarning, match="^products involving .* 'str'"):
        assert u.cm * "kg" == u.cm * u.kg


def test_unit_division_by_string():
    with pytest.warns(
        AstropyDeprecationWarning,
        match=(
            "^divisions involving a unit and a 'str' instance are deprecated since "
            r"v7\.1\. Convert 'kg' to a unit explicitly\.$"
        ),
    ):
        assert "kg" / u.cm == u.kg / u.cm
    with pytest.warns(AstropyDeprecationWarning, match="^divisions involving .* 'str'"):
        assert u.cm / "kg" == u.cm / u.kg


def test_sorted_bases():
    """See #1616."""
    assert (u.m * u.Jy).bases == (u.Jy * u.m).bases


def test_megabit():
    """See #1543"""
    assert u.Mbit is u.Mb
    assert u.megabit is u.Mb

    assert u.Mbyte is u.MB
    assert u.megabyte is u.MB


def test_composite_unit_get_format_name():
    """See #1576"""
    unit1 = u.Unit("nrad/s")
    unit2 = u.Unit("Hz(1/2)")
    assert str(u.CompositeUnit(1, [unit1, unit2], [1, -1])) == "nrad / (Hz(1/2) s)"


def test_unicode_policy():
    from astropy.tests.helper import assert_follows_unicode_guidelines

    assert_follows_unicode_guidelines(u.degree, roundtrip=u.__dict__)


def test_suggestions():
    for search, matches in [
        ("microns", "micron"),
        ("s/microns", "micron"),
        ("M", "m"),
        ("metre", "meter"),
        ("angstroms", "Angstrom or angstrom"),
        ("milimeter", "millimeter"),  # codespell:ignore milimeter
        ("ångström", "Angstrom, angstrom, mAngstrom or mangstrom"),
        ("kev", "EV, eV, kV or keV"),
    ]:
        with pytest.raises(ValueError, match=f"Did you mean {matches}"):
            u.Unit(search)


def test_fits_hst_unit():
    """See #1911."""
    with pytest.warns(u.UnitsWarning, match="multiple slashes") as w:
        x = u.Unit("erg /s /cm**2 /angstrom")
    assert x == u.erg * u.s**-1 * u.cm**-2 * u.angstrom**-1
    assert len(w) == 1


def test_barn_prefixes():
    """Regression test for https://github.com/astropy/astropy/issues/3753"""

    assert u.fbarn is u.femtobarn
    assert u.pbarn is u.picobarn


def test_fractional_powers():
    """See #2069"""
    m = 1e9 * u.Msun
    tH = 1.0 / (70.0 * u.km / u.s / u.Mpc)
    vc = 200 * u.km / u.s

    x = (c.G**2 * m**2 * tH.cgs) ** Fraction(1, 3) / vc
    v1 = x.to("pc")

    x = (c.G**2 * m**2 * tH) ** Fraction(1, 3) / vc
    v2 = x.to("pc")

    x = (c.G**2 * m**2 * tH.cgs) ** (1.0 / 3.0) / vc
    v3 = x.to("pc")

    x = (c.G**2 * m**2 * tH) ** (1.0 / 3.0) / vc
    v4 = x.to("pc")

    assert_allclose(v1, v2)
    assert_allclose(v2, v3)
    assert_allclose(v3, v4)

    x = u.m ** (1.0 / 101.0)
    assert isinstance(x.powers[0], float)

    x = u.m ** (3.0 / 7.0)
    assert isinstance(x.powers[0], Fraction)
    assert x.powers[0].numerator == 3
    assert x.powers[0].denominator == 7

    x = u.cm ** Fraction(1, 2) * u.cm ** Fraction(2, 3)
    assert isinstance(x.powers[0], Fraction)
    assert x.powers[0] == Fraction(7, 6)

    # Regression test for #9258 (avoid fractions with crazy denominators).
    x = (u.TeV ** (-2.2)) ** (1 / -2.2)
    assert isinstance(x.powers[0], int)
    assert x.powers[0] == 1
    x = (u.TeV ** (-2.2)) ** (1 / -6.6)
    assert isinstance(x.powers[0], Fraction)
    assert x.powers[0] == Fraction(1, 3)


def test_large_fractional_powers():
    # Ensure we keep fractions if the user passes them in
    # and the powers are themselves simple fractions.
    x1 = u.m ** Fraction(10, 11)
    assert isinstance(x1.powers[0], Fraction)
    assert x1.powers[0] == Fraction(10, 11)
    x2 = x1 ** Fraction(10, 11)
    assert isinstance(x2.powers[0], Fraction)
    assert x2.powers[0] == Fraction(100, 121)
    # Check powers that can be represented as simple fractions.
    x3 = x2**0.5
    assert isinstance(x3.powers[0], Fraction)
    assert x3.powers[0] == Fraction(50, 121)
    x4 = x3 ** (5 / 11)
    assert isinstance(x4.powers[0], Fraction)
    assert x4.powers[0] == Fraction(250, 1331)
    x5 = x4**1.1
    assert isinstance(x5.powers[0], Fraction)
    assert x5.powers[0] == Fraction(25, 121)


def test_sqrt_mag():
    sqrt_mag = u.mag**0.5
    assert hasattr(sqrt_mag.decompose().scale, "imag")
    assert (sqrt_mag.decompose()) ** 2 == u.mag


def test_composite_compose():
    # Issue #2382
    composite_unit = u.s.compose(units=[u.Unit("s")])[0]
    u.s.compose(units=[composite_unit])


def test_data_quantities():
    assert u.byte.is_equivalent(u.bit)


def test_compare_with_none():
    # Ensure that equality comparisons with `None` work, and don't
    # raise exceptions.  We are deliberately not using `is None` here
    # because that doesn't trigger the bug.  See #3108.
    assert not (u.m == None)
    assert u.m != None


def test_sanitize_power_detect_fraction():
    frac = utils.sanitize_power(1.1666666666666665)
    assert isinstance(frac, Fraction)
    assert frac.numerator == 7
    assert frac.denominator == 6


def test_sanitize_power_zero_like():
    # Regression test for #16779 - 0 should always be an int after sanitizing
    power = utils.sanitize_power(np.float64(0))
    assert type(power) is int
    assert power == 0


def test_complex_fractional_rounding_errors():
    # See #3788

    kappa = 0.34 * u.cm**2 / u.g
    r_0 = 886221439924.7849 * u.cm
    q = 1.75
    rho_0 = 5e-10 * u.solMass / u.solRad**3
    y = 0.5
    beta = 0.19047619047619049
    a = 0.47619047619047628
    m_h = 1e6 * u.solMass

    t1 = 2 * c.c / (kappa * np.sqrt(np.pi))
    t2 = (r_0**-q) / (rho_0 * y * beta * (a * c.G * m_h) ** 0.5)

    result = (t1 * t2) ** -0.8

    assert result.unit.physical_type == "length"
    result.to(u.solRad)


def test_fractional_rounding_errors_simple():
    x = (u.m**1.5) ** Fraction(4, 5)
    assert isinstance(x.powers[0], Fraction)
    assert x.powers[0].numerator == 6
    assert x.powers[0].denominator == 5


def test_enable_unit_groupings():
    from astropy.units import cds

    with cds.enable():
        assert cds.geoMass in u.kg.find_equivalent_units()

    from astropy.units import imperial

    with imperial.enable():
        assert imperial.inch in u.m.find_equivalent_units()


def test_raise_to_negative_power():
    """Test that order of bases is changed when raising to negative power.

    Regression test for https://github.com/astropy/astropy/issues/8260
    """
    m2s2 = u.m**2 / u.s**2
    spm = m2s2 ** (-1 / 2)
    assert spm.bases == [u.s, u.m]
    assert spm.powers == [1, -1]
    assert spm == u.s / u.m


@pytest.mark.parametrize(
    "name, factor",
    [
        pytest.param(name, factor, id=name)
        for name, factor in [
            ("quetta", 1e30),
            ("ronna", 1e27),
            ("yotta", 1e24),
            ("zetta", 1e21),
            ("exa", 1e18),
            ("peta", 1e15),
            ("tera", 1e12),
            ("giga", 1e9),
            ("mega", 1e6),
            ("kilo", 1e3),
            ("deca", 1e1),
            ("deka", 1e1),  # American spelling of deca
            ("deci", 1e-1),
            ("centi", 1e-2),
            ("milli", 1e-3),
            ("micro", 1e-6),
            ("nano", 1e-9),
            ("pico", 1e-12),
            ("femto", 1e-15),
            ("atto", 1e-18),
            ("zepto", 1e-21),
            ("yocto", 1e-24),
            ("ronto", 1e-27),
            ("quecto", 1e-30),
        ]
    ],
)
def test_si_prefix_names(name, factor):
    base = 1 * u.s
    quantity_from_name = base.to(f"{name}second")
    assert u.isclose(quantity_from_name, base)
    assert np.isclose(base.value / quantity_from_name.value, factor, atol=0)


@pytest.mark.parametrize(
    "symbol, factor",
    [
        pytest.param(symbol, factor, id=symbol)
        for symbol, factor in [
            ("Q", 1e30),
            ("R", 1e27),
            ("Y", 1e24),
            ("Z", 1e21),
            ("E", 1e18),
            ("P", 1e15),
            ("T", 1e12),
            ("G", 1e9),
            ("M", 1e6),
            ("k", 1e3),
            ("da", 1e1),
            ("d", 1e-1),
            ("c", 1e-2),
            ("m", 1e-3),
            ("\N{MICRO SIGN}", 1e-6),
            ("\N{GREEK SMALL LETTER MU}", 1e-6),
            ("u", 1e-6),
            ("n", 1e-9),
            ("p", 1e-12),
            ("f", 1e-15),
            ("a", 1e-18),
            ("z", 1e-21),
            ("y", 1e-24),
            ("r", 1e-27),
            ("q", 1e-30),
        ]
    ],
)
def test_si_prefix_symbols(symbol, factor):
    base = 1 * u.m
    quantity_from_symbol = base.to(f"{symbol}m")
    assert u.isclose(quantity_from_symbol, base)
    assert np.isclose(base.value / quantity_from_symbol.value, factor, atol=0)


@pytest.mark.parametrize(
    "name,symbol,factor",
    [
        pytest.param(name, symbol, factor, id=name)
        for name, symbol, factor in [
            ("kibi", "Ki", 2**10),
            ("mebi", "Mi", 2**20),
            ("gibi", "Gi", 2**30),
            ("tebi", "Ti", 2**40),
            ("pebi", "Pi", 2**50),
            ("exbi", "Ei", 2**60),
            # We now switch to float factors because with numpy < 2.0
            # np.isclose() doesn't like ints this large
            ("zebi", "Zi", 2.0**70),
            ("yobi", "Yi", 2.0**80),
        ]
    ],
)
def test_si_binary_prefixes(name, symbol, factor):
    base = 1 * u.byte
    quantity_from_name = base.to(f"{name}byte")
    assert u.isclose(quantity_from_name, base)
    assert np.isclose(base.value / quantity_from_name.value, factor, atol=0)

    quantity_from_symbol = base.to(f"{symbol}B")
    assert u.isclose(quantity_from_symbol, base)
    assert np.isclose(base.value / quantity_from_symbol.value, factor, atol=0)


def test_cm_uniqueness():
    # Ensure we have defined cm only once; see gh-15200.
    assert u.si.cm is u.cgs.cm is u.cm
    assert str(u.si.cm / u.cgs.cm) == ""  # was cm / cm


@pytest.mark.parametrize("unit, power", [(u.m, 2), (u.m, 3), (u.m / u.s, 9)])
def test_hash_represents_unit(unit, power):
    # Regression test for gh-16055
    tu = (unit**power) ** (1 / power)
    assert hash(tu) == hash(unit)
    tu2 = (unit ** (1 / power)) ** power
    assert hash(tu2) == hash(unit)


@pytest.mark.skipif(not HAS_ARRAY_API_STRICT, reason="tests array_api_strict")
def test_array_api_strict_arrays():
    # Ensure strict array api arrays can be passed in/out of Unit.to()
    # Note that those have non-standard dtype.
    import array_api_strict as xp

    data1 = xp.asarray([1.0, 2.0, 3.0])
    data2 = u.m.to(u.km, value=data1)
    assert isinstance(data2, type(data1))
    assert_allclose(data2, [0.001, 0.002, 0.003])

    data3 = u.K.to(u.deg_C, value=data1, equivalencies=u.temperature())
    assert isinstance(data3, type(data1))
    assert_allclose(data3, [-272.15, -271.15, -270.15])


@pytest.mark.skipif(not HAS_DASK, reason="tests dask.array")
def test_dask_arrays():
    # Make sure that dask arrays can be passed in/out of Unit.to()

    from dask import array as da

    data1 = da.from_array([1, 2, 3])

    data2 = u.m.to(u.km, value=data1)

    assert isinstance(data2, da.core.Array)

    assert_allclose(data2.compute(), [0.001, 0.002, 0.003])

    data3 = u.K.to(u.deg_C, value=data1, equivalencies=u.temperature())

    assert isinstance(data3, da.core.Array)

    assert_allclose(data3.compute(), [-272.15, -271.15, -270.15])


def test_get_format_name_deprecation():
    with pytest.warns(AstropyDeprecationWarning, match=r"Use to_string\(\) instead\.$"):
        assert u.m.get_format_name("fits") == "m"


def test_comparison_dimensionless_with_np_ma_masked():
    # Found to be a problem indirectly in gh-17047;
    # The path np.ma.masked.__eq__(u.dimensionless_unscaled)
    # used to give a ZeroDivisionError.
    comparison = u.dimensionless_unscaled == np.ma.masked
    assert comparison is np.ma.masked


def test_error_on_conversion_of_zero_to_unit():
    # Found to be a problem indirectly in gh-17047; we allow conversion
    # of numbers to units, but should not allow 0.
    with pytest.raises(u.UnitScaleError, match="cannot create.*scale of 0"):
        u.Unit(0)
    with pytest.raises(u.UnitScaleError, match="cannot create.*scale of 0"):
        u.dimensionless_unscaled.to(0)
    # Also check some that do work.
    assert u.dimensionless_unscaled.to(0.125) == 8
    assert u.dimensionless_unscaled.to(8) == 0.125


@pytest.mark.parametrize(
    "unsanitized,sanitized",
    [
        pytest.param(complex(2, FLOAT_EPS), 2, id="almost_real_complex"),
        pytest.param(complex(FLOAT_EPS, 2), 2j, id="almost_imaginary_complex"),
    ],
)
def test_scale_sanitization(unsanitized, sanitized):
    assert u.CompositeUnit(unsanitized, [u.m], [1]).scale == sanitized


@pytest.mark.parametrize(
    "scale",
    [
        5,
        10.0,
        7 + 3j,
        Fraction(1, 3),
        np.int32(100),
        np.float32(0.01),
        np.complex128(1 - 4j),
    ],
    ids=type,
)
def test_dimensionless_scale_factor_types(scale):
    # Regression test for #17355 - Unit did not accept all scale factor
    # types that CompositeUnit accepted
    assert u.Unit(scale) == u.CompositeUnit(scale, [], [])


# No need to test everything defined in required_by_vounit, the following few are
# representative enough.
required_by_vounit_parametrization = pytest.mark.parametrize(
    "unit", [GsolLum, ksolMass, nsolRad], ids=lambda x: x.name
)


@required_by_vounit_parametrization
def test_required_by_vounit_not_in_main_namespace(unit):
    with pytest.raises(
        AttributeError,
        match=rf"^module 'astropy\.units' has no attribute '{unit.name}'$",
    ):
        getattr(u, unit.name)


@required_by_vounit_parametrization
def test_required_by_vounit_parsing(unit):
    assert u.Unit(unit.name) is unit


@required_by_vounit_parametrization
def test_required_by_vounit_not_in_find_equivalent_units(unit):
    assert unit not in unit.represents.bases[0].find_equivalent_units()
