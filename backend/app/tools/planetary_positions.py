"""Low-precision planetary ephemeris - pure Python, no external dependencies
or network calls (same "runs with just a Python virtualenv" spirit as every
other tool in this package).

Implements the classic low-precision method popularized by Paul Schlyter
("How to compute planetary positions") - Keplerian orbital elements as linear
functions of days-since-J2000, solved via Newton's method for eccentric
anomaly, combined into geocentric ecliptic longitudes. Accurate to roughly
0.5-1 degree, which is what this app needs: the Astrological Analyst
(app/agents/analysts/astro.py) is an explicitly traditional/folklore-based
heuristic overlay, not a navigation-grade ephemeris.

Sanity check for anyone auditing the orbital element constants below: each
body's Mdot (mean daily motion) implies an orbital period of 360/Mdot days,
which should match its real sidereal period - Mercury ~88d, Venus ~224.7d,
Earth/Sun ~365.25d, Mars ~687d, Jupiter ~4332.6d (11.86y), Saturn ~10759d
(29.46y), Moon (anomalistic) ~27.55d, Moon's node regression ~6798d (18.6y).
See tests/test_planetary_positions.py for these checks encoded as tests.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------- angle helpers (degrees in, degrees/floats out)


def _sind(deg: float) -> float:
    return math.sin(math.radians(deg))


def _cosd(deg: float) -> float:
    return math.cos(math.radians(deg))


def _atan2d(y: float, x: float) -> float:
    return math.degrees(math.atan2(y, x))


def _norm360(deg: float) -> float:
    return deg % 360.0


# ---------------------------------------------------------------- epoch / orbital elements

def days_since_epoch(when: dt.datetime) -> float:
    """Schlyter's day-number: d=0.0 at 2000 Jan 0.0 UT (= 1999-12-31 00:00),
    so 2000-01-01 00:00 UT -> d=1.0. `when` must be UTC (naive treated as UTC)."""
    if when.tzinfo is not None:
        when = when.astimezone(dt.timezone.utc)
    y, m, day = when.year, when.month, when.day
    d = 367 * y - 7 * (y + (m + 9) // 12) // 4 + 275 * m // 9 + day - 730530
    frac_day = (when.hour + when.minute / 60.0 + when.second / 3600.0) / 24.0
    return d + frac_day


# Orbital elements at epoch + rate per day: (N0, Ndot, i0, idot, w0, wdot, a, e0, edot, M0, Mdot)
# "Sun" here means the Sun's apparent geocentric orbit (N=i=0 by construction,
# equivalent to Earth's heliocentric orbit) - used both for the Sun's own
# position and, negated, for Earth's heliocentric position (needed to convert
# the other planets' heliocentric coordinates to geocentric).
_ELEMENTS: dict[str, tuple[float, float, float, float, float, float, float, float, float, float, float]] = {
    "sun":     (0.0, 0.0, 0.0, 0.0, 282.9404, 4.70935e-5, 1.000000, 0.016709, -1.151e-9, 356.0470, 0.9856002585),
    "moon":    (125.1228, -0.0529538083, 5.1454, 0.0, 318.0634, 0.1643573223, 60.2666, 0.054900, 0.0, 115.3654, 13.0649929509),
    "mercury": (48.3313, 3.24587e-5, 7.0047, 5.00e-8, 29.1241, 1.01444e-5, 0.387098, 0.205635, 5.59e-10, 168.6562, 4.0923344368),
    "venus":   (76.6799, 2.46590e-5, 3.3946, 2.75e-8, 54.8910, 1.38374e-5, 0.723330, 0.006773, -1.302e-9, 48.0052, 1.6021302244),
    "mars":    (49.5574, 2.11081e-5, 1.8497, -1.78e-8, 286.5016, 2.92961e-5, 1.523688, 0.093405, 2.516e-9, 18.6021, 0.5240207766),
    "jupiter": (100.4542, 2.76854e-5, 1.3030, -1.557e-7, 273.8777, 1.64505e-5, 5.20256, 0.048498, 4.469e-9, 19.8950, 0.0830853001),
    "saturn":  (113.6634, 2.38980e-5, 2.4886, -1.081e-7, 339.3939, 2.97661e-5, 9.55475, 0.055546, -9.499e-9, 316.9670, 0.0334442282),
}

_PLANETS_WITH_RETROGRADE = ("mercury", "venus", "mars", "jupiter", "saturn")


def _elements_at(body: str, d: float) -> tuple[float, float, float, float, float, float]:
    N0, Ndot, i0, idot, w0, wdot, a, e0, edot, M0, Mdot = _ELEMENTS[body]
    N = N0 + Ndot * d
    i = i0 + idot * d
    w = w0 + wdot * d
    e = e0 + edot * d
    M = M0 + Mdot * d
    return N, i, w, a, e, M


def _solve_kepler(m_deg: float, e: float, tol: float = 1e-6, max_iter: int = 30) -> float:
    """Newton's method for eccentric anomaly E from mean anomaly M (degrees) and
    eccentricity e. Returns E in degrees."""
    m = math.radians(m_deg)
    ecc_anom = m + e * math.sin(m) * (1.0 + e * math.cos(m))  # standard 2nd-order starting guess
    for _ in range(max_iter):
        delta_m = ecc_anom - e * math.sin(ecc_anom) - m
        delta_e = delta_m / (1.0 - e * math.cos(ecc_anom))
        ecc_anom -= delta_e
        if abs(delta_e) < tol:
            break
    return math.degrees(ecc_anom)


def _sun_geocentric(d: float) -> tuple[float, float, float]:
    """Returns (longitude_deg, x, y) - the Sun's geocentric ecliptic position
    (z=0 by construction, N=i=0)."""
    _, _, w, a, e, m = _elements_at("sun", d)
    big_e = _solve_kepler(m, e)
    xv = a * (_cosd(big_e) - e)
    yv = a * (math.sqrt(max(0.0, 1 - e * e)) * _sind(big_e))
    v = _atan2d(yv, xv)
    r = math.hypot(xv, yv)
    lon = _norm360(v + w)
    return lon, r * _cosd(lon), r * _sind(lon)


def _moon_geocentric(d: float) -> float:
    N, i, w, a, e, m = _elements_at("moon", d)
    big_e = _solve_kepler(m, e)
    xv = a * (_cosd(big_e) - e)
    yv = a * (math.sqrt(max(0.0, 1 - e * e)) * _sind(big_e))
    v = _atan2d(yv, xv)
    r = math.hypot(xv, yv)
    xh = r * (_cosd(N) * _cosd(v + w) - _sind(N) * _sind(v + w) * _cosd(i))
    yh = r * (_sind(N) * _cosd(v + w) + _cosd(N) * _sind(v + w) * _cosd(i))
    return _norm360(_atan2d(yh, xh))


def _planet_geocentric_longitude(body: str, d: float, sun_xy: tuple[float, float]) -> float:
    N, i, w, a, e, m = _elements_at(body, d)
    big_e = _solve_kepler(m, e)
    xv = a * (_cosd(big_e) - e)
    yv = a * (math.sqrt(max(0.0, 1 - e * e)) * _sind(big_e))
    v = _atan2d(yv, xv)
    r = math.hypot(xv, yv)
    xh = r * (_cosd(N) * _cosd(v + w) - _sind(N) * _sind(v + w) * _cosd(i))
    yh = r * (_sind(N) * _cosd(v + w) + _cosd(N) * _sind(v + w) * _cosd(i))
    xs, ys = sun_xy
    # Geocentric = heliocentric_planet - heliocentric_earth, and
    # heliocentric_earth = -(xs, ys) since (xs, ys) is the Sun's geocentric
    # position (Earth's heliocentric position negated).
    xg = xh + xs
    yg = yh + ys
    return _norm360(_atan2d(yg, xg))


def longitude_of(body: str, when: dt.datetime) -> float:
    """Geocentric ecliptic (tropical) longitude in degrees [0, 360) for one
    body ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")."""
    d = days_since_epoch(when)
    if body == "sun":
        lon, _, _ = _sun_geocentric(d)
        return lon
    if body == "moon":
        return _moon_geocentric(d)
    _, sx, sy = _sun_geocentric(d)
    return _planet_geocentric_longitude(body, d, (sx, sy))


def is_retrograde(body: str, when: dt.datetime) -> bool:
    """Sun and Moon are never retrograde (geocentrically) - true for every
    other supported body. Detected by comparing longitude a day apart -
    genuinely emerges from the orbital mechanics rather than being looked up
    from a hardcoded date table."""
    if body not in _PLANETS_WITH_RETROGRADE:
        return False
    lon_now = longitude_of(body, when)
    lon_prev = longitude_of(body, when - dt.timedelta(days=1))
    diff = (lon_now - lon_prev + 540.0) % 360.0 - 180.0  # signed diff in (-180, 180]
    return diff < 0


# Lahiri (chitrapaksha) ayanamsa - linear approximation pinned to its
# well-documented ~23.85 deg value at epoch 2000 and the ~50.29"/year
# (0.013972 deg/year) precession rate. Good to a few arcminutes over decades -
# ample for nakshatra/rashi bucketing, not for precision natal charts.
_AYANAMSA_AT_2000 = 23.85
_AYANAMSA_RATE_PER_YEAR = 0.013972


def ayanamsa(when: dt.datetime) -> float:
    year_frac = when.year + (when.timetuple().tm_yday - 1) / 365.25
    return _AYANAMSA_AT_2000 + _AYANAMSA_RATE_PER_YEAR * (year_frac - 2000.0)


def sidereal_longitude(tropical_longitude_deg: float, when: dt.datetime) -> float:
    return _norm360(tropical_longitude_deg - ayanamsa(when))


NAKSHATRAS = (
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu", "Pushya", "Ashlesha",
    "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
    "Uttara Bhadrapada", "Revati",
)
_NAKSHATRA_SPAN = 360.0 / 27  # 13 deg 20'

RASHIS = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)
_RASHI_SPAN = 30.0


def nakshatra_of(sidereal_deg: float) -> str:
    return NAKSHATRAS[int(_norm360(sidereal_deg) // _NAKSHATRA_SPAN) % 27]


def rashi_of(sidereal_deg: float) -> str:
    return RASHIS[int(_norm360(sidereal_deg) // _RASHI_SPAN) % 12]


_MOON_PHASE_NAMES = (
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
)


def moon_phase(sun_lon: float, moon_lon: float) -> tuple[str, float, bool]:
    """Returns (phase_name, illumination_fraction, is_waxing)."""
    phase_angle = _norm360(moon_lon - sun_lon)
    illumination = round((1 - _cosd(phase_angle)) / 2, 3)
    is_waxing = phase_angle < 180.0
    name = _MOON_PHASE_NAMES[int(phase_angle // 45.0) % 8]
    return name, illumination, is_waxing


@dataclass
class PlanetarySnapshot:
    when: dt.datetime
    ayanamsa_deg: float
    tropical_longitude: dict[str, float] = field(default_factory=dict)
    sidereal_longitude: dict[str, float] = field(default_factory=dict)
    retrograde: dict[str, bool] = field(default_factory=dict)
    moon_nakshatra: str = ""
    moon_rashi: str = ""
    sun_rashi: str = ""
    jupiter_rashi: str = ""
    moon_phase_name: str = ""
    moon_illumination: float = 0.0
    moon_waxing: bool = True


_BODIES = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")


def get_snapshot(when: dt.datetime | None = None) -> PlanetarySnapshot:
    when = when or dt.datetime.now(dt.timezone.utc)
    tropical = {body: longitude_of(body, when) for body in _BODIES}
    ayan = ayanamsa(when)
    sidereal = {body: sidereal_longitude(lon, when) for body, lon in tropical.items()}
    retro = {body: is_retrograde(body, when) for body in _PLANETS_WITH_RETROGRADE}
    phase_name, illumination, waxing = moon_phase(tropical["sun"], tropical["moon"])

    return PlanetarySnapshot(
        when=when,
        ayanamsa_deg=round(ayan, 4),
        tropical_longitude={k: round(v, 3) for k, v in tropical.items()},
        sidereal_longitude={k: round(v, 3) for k, v in sidereal.items()},
        retrograde=retro,
        moon_nakshatra=nakshatra_of(sidereal["moon"]),
        moon_rashi=rashi_of(sidereal["moon"]),
        sun_rashi=rashi_of(sidereal["sun"]),
        jupiter_rashi=rashi_of(sidereal["jupiter"]),
        moon_phase_name=phase_name,
        moon_illumination=illumination,
        moon_waxing=waxing,
    )
