"""MGI 1901 / Balkans zone 7 (the national grid of the NTES register) -> WGS84 lon/lat, one smooth transformation for the whole country.

Transverse Mercator on the Bessel 1841 ellipsoid (central meridian 21 E, scale 0.9999, false easting 7,500,000), followed by the datum shift
MGI 1901 -> WGS84 written as a small smooth offset (dlon, dlat as a function of position). The offset was fitted on 70,000 vertices of the old
(PROJ) conversion in the part of the country where PROJ used a single operation (maximum fit error about 5 m) and checked against the Bulgarian
and Albanian borders (median distance 56 m / 116 m, the limit of those datasets). PROJ, by contrast, switched to a different operation inside
a rectangle in the north-west, which is what tore the settlement shapes there.
"""
import numpy as np
A_B, F_B = 6377397.155, 1 / 299.1528128
def tm_inverse(x, y, a=A_B, f=F_B, lon0=21.0, k0=0.9999, fe=7500000.0, fn=0.0):
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    x = np.asarray(x, float) - fe; y = np.asarray(y, float) - fn
    e1 = (1 - np.sqrt(1 - e2)) / (1 + np.sqrt(1 - e2))
    mu = (y / k0) / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    p1 = mu + (3*e1/2 - 27*e1**3/32)*np.sin(2*mu) + (21*e1**2/16 - 55*e1**4/32)*np.sin(4*mu) + (151*e1**3/96)*np.sin(6*mu) + (1097*e1**4/512)*np.sin(8*mu)
    s, c, t = np.sin(p1), np.cos(p1), np.tan(p1)
    N1 = a / np.sqrt(1 - e2*s**2); T1 = t**2; C1 = ep2*c**2; R1 = a*(1 - e2)/(1 - e2*s**2)**1.5; D = x/(N1*k0)
    lat = p1 - (N1*t/R1)*(D**2/2 - (5 + 3*T1 + 10*C1 - 4*C1**2 - 9*ep2)*D**4/24 + (61 + 90*T1 + 298*C1 + 45*T1**2 - 252*ep2 - 3*C1**2)*D**6/720)
    lon = np.radians(lon0) + (D - (1 + 2*T1 + C1)*D**3/6 + (5 - 2*C1 + 28*T1 - 3*C1**2 + 8*ep2 + 24*T1**2)*D**5/120)/c
    return np.degrees(lon), np.degrees(lat)
# (raw - WGS84) offset in degrees = c0 + c1*(lon-21.7) + c2*(lat-41.5)
CX = (5.40084331e-03, 5.42783247e-06, 5.12325227e-06)
CY = (-4.23519302e-04, -5.78440526e-06, 2.82442591e-05)
def to_wgs84(x, y):
    lon, lat = tm_inverse(x, y)
    u, v = lon - 21.7, lat - 41.5
    return lon - (CX[0] + CX[1]*u + CX[2]*v), lat - (CY[0] + CY[1]*u + CY[2]*v)
