import 'dart:math' as math;

import 'package:latlong2/latlong.dart';

double geometryLengthMeters(List<LatLng> points) {
  if (points.length < 2) return 0;
  const distance = Distance();
  var total = 0.0;
  for (var index = 1; index < points.length; index++) {
    total += distance.as(LengthUnit.Meter, points[index - 1], points[index]);
  }
  return total;
}

double polygonAreaSquareMeters(List<LatLng> points) {
  if (points.length < 3) return 0;
  const earthRadius = 6378137.0;
  var sum = 0.0;
  for (var index = 0; index < points.length; index++) {
    final current = points[index];
    final next = points[(index + 1) % points.length];
    final currentLat = current.latitude * math.pi / 180;
    final nextLat = next.latitude * math.pi / 180;
    final deltaLongitude = (next.longitude - current.longitude) * math.pi / 180;
    sum += deltaLongitude * (2 + math.sin(currentLat) + math.sin(nextLat));
  }
  return (sum * earthRadius * earthRadius / 2).abs();
}
