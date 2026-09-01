import 'dart:io';
import 'dart:typed_data';

import 'package:geoimage/geoimage.dart';
import 'package:image/image.dart' as image;
import 'package:flutter_map/flutter_map.dart' show LatLngBounds;
import 'package:latlong2/latlong.dart';
import 'package:proj4dart/proj4dart.dart';

class GeoRasterOverlay {
  const GeoRasterOverlay({
    required this.pngBytes,
    required this.bounds,
    required this.srid,
  });

  final Uint8List pngBytes;
  final LatLngBounds bounds;
  final int srid;
}

class GeoRasterService {
  Future<GeoRasterOverlay> loadGeoTiff(String filePath) async {
    final geoImage = GeoImage(File(filePath));
    geoImage.read();
    final info = geoImage.geoInfo;
    final decodedImage = geoImage.image;
    if (info == null || decodedImage == null) {
      throw StateError('GeoTIFF sem extensão geográfica legível.');
    }
    final srid = info.srid;
    if (srid <= 0) {
      throw StateError('GeoTIFF sem EPSG identificável.');
    }
    final envelope = info.worldEnvelope;
    final southWest = _toWgs84(
      envelope.getMinX(),
      envelope.getMinY(),
      srid,
    );
    final northEast = _toWgs84(
      envelope.getMaxX(),
      envelope.getMaxY(),
      srid,
    );
    return GeoRasterOverlay(
      pngBytes: Uint8List.fromList(image.encodePng(decodedImage)),
      bounds: LatLngBounds(southWest, northEast),
      srid: srid,
    );
  }

  LatLng _toWgs84(double x, double y, int srid) {
    if (srid == 4326) return LatLng(y, x);
    final source = Projection.get('EPSG:$srid');
    final target = Projection.get('EPSG:4326');
    if (source == null || target == null) {
      throw StateError(
        'EPSG:$srid não está disponível no conversor local. Use MBTiles ou processe o raster no servidor.',
      );
    }
    final transformed = source.transform(target, Point(x: x, y: y));
    return LatLng(transformed.y, transformed.x);
  }
}
