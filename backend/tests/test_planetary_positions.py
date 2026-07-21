"""Tests for the pure-Python low-precision ephemeris (app/tools/planetary_positions.py)
- no network, no LLM key required.

These aren't testing against a precision reference ephemeris (this module
explicitly isn't one - see its module docstring); they're sanity checks that
the orbital-element constants and Kepler-equation solver produce physically
plausible behavior, cross-checked against well-known real-world astronomical
facts (orbital periods, Earth's early-January perihelion, lunar nodal
regression period, Mercury's typical retrograde frequency)."""

from __future__ import annotations

import datetime as dt

from app.tools import planetary_positions as pp

# Real sidereal/anomalistic orbital periods (days), for cross-checking the
# Mdot (mean daily motion) constants: implied_period = 360 / Mdot.
_KNOWN_PERIODS_DAYS = {
    "mercury": 87.969,
    "venus": 224.701,
    "sun": 365.256,  # Earth's own period, via the Sun's apparent geocentric orbit
    "mars": 686.980,
    "jupiter": 4332.589,
    "saturn": 10759.22,
    "moon": 27.555,  # anomalistic month
}


def test_day_number_epoch_matches_schlyter_convention():
    # Schlyter's day-number: d=0.0 at 2000 Jan 0.0 UT (1999-12-31 00:00),
    # so 2000-01-01 00:00 UT -> d=1.0.
    assert pp.days_since_epoch(dt.datetime(2000, 1, 1)) == 1.0


def test_mean_motions_match_known_orbital_periods():
    for body, expected_days in _KNOWN_PERIODS_DAYS.items():
        _, _, _, _, _, _, _, _, _, _, mdot = pp._ELEMENTS[body]
        implied_days = 360.0 / mdot
        assert abs(implied_days - expected_days) / expected_days < 0.005, (body, implied_days, expected_days)


def test_moon_node_regression_matches_known_18_6_year_cycle():
    _, ndot, *_ = pp._ELEMENTS["moon"]
    years = 360.0 / abs(ndot) / 365.25
    assert 18.0 < years < 19.0


def test_sun_perihelion_lands_in_early_january():
    """Earth's real perihelion is ~Jan 3-4 - the Sun's mean anomaly (as seen
    from Earth) should cross 0 (mod 360) right around then."""
    for day in range(1, 8):
        d = pp.days_since_epoch(dt.datetime(2000, 1, day))
        _, _, _, _, _, m = pp._elements_at("sun", d)
        if m % 360 < 2 or m % 360 > 358:
            return
    raise AssertionError("Sun's mean anomaly never crossed 0 in the first week of January")


def test_longitude_is_always_in_valid_range():
    when = dt.datetime(2026, 7, 21, 12, 0, tzinfo=dt.timezone.utc)
    for body in ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"):
        lon = pp.longitude_of(body, when)
        assert 0.0 <= lon < 360.0


def test_sun_advances_roughly_one_degree_per_day():
    t0 = dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
    lon0 = pp.longitude_of("sun", t0)
    lon7 = pp.longitude_of("sun", t0 + dt.timedelta(days=7))
    delta = (lon7 - lon0) % 360
    assert 6.0 < delta < 8.0  # ~360/365.25 * 7 = 6.9 deg


def test_sun_and_moon_are_never_retrograde():
    when = dt.datetime(2026, 7, 21, tzinfo=dt.timezone.utc)
    assert pp.is_retrograde("sun", when) is False
    assert pp.is_retrograde("moon", when) is False


def test_mercury_goes_retrograde_a_realistic_number_of_times_per_year():
    """Mercury has ~3-4 retrograde periods (~3 weeks each) per year in
    reality - the sign of a working (not just always-True/always-False)
    retrograde detector, not a claim about any specific date."""
    start = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    days_retrograde = 0
    transitions = 0
    prev = None
    for i in range(365):
        retro = pp.is_retrograde("mercury", start + dt.timedelta(days=i))
        if retro:
            days_retrograde += 1
        if prev is not None and retro != prev:
            transitions += 1
        prev = retro
    assert 40 <= days_retrograde <= 90
    assert 4 <= transitions <= 10  # 2-5 retrograde windows (each has an enter + exit transition)


def test_nakshatra_and_rashi_bucket_boundaries():
    assert pp.nakshatra_of(0.0) == "Ashwini"
    assert pp.nakshatra_of(13.3) == "Ashwini"
    assert pp.nakshatra_of(13.4) == "Bharani"
    assert pp.nakshatra_of(359.9) == "Revati"
    assert pp.rashi_of(0.0) == "Aries"
    assert pp.rashi_of(29.9) == "Aries"
    assert pp.rashi_of(30.1) == "Taurus"


def test_moon_phase_new_and_full():
    name, illumination, waxing = pp.moon_phase(sun_lon=100.0, moon_lon=100.0)
    assert name == "New Moon"
    assert illumination < 0.05
    name, illumination, waxing = pp.moon_phase(sun_lon=100.0, moon_lon=280.0)
    assert name == "Full Moon"
    assert illumination > 0.95


def test_ayanamsa_is_in_a_plausible_range_for_present_day():
    # Lahiri ayanamsa is around 24 deg in the mid-2020s.
    value = pp.ayanamsa(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
    assert 23.5 < value < 25.0


def test_get_snapshot_returns_consistent_fields():
    snap = pp.get_snapshot(dt.datetime(2026, 7, 21, 12, 0, tzinfo=dt.timezone.utc))
    assert set(snap.tropical_longitude) == {"sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"}
    assert snap.moon_nakshatra in pp.NAKSHATRAS
    assert snap.moon_rashi in pp.RASHIS
    assert snap.moon_phase_name in pp._MOON_PHASE_NAMES
    assert isinstance(snap.retrograde["mercury"], bool)
    assert "mercury" in snap.retrograde and "sun" not in snap.retrograde  # Sun/Moon excluded, never retrograde
