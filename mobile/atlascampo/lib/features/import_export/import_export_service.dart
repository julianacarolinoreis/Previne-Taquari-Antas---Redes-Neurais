import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:file_picker/file_picker.dart';
import 'package:image_picker/image_picker.dart';
import 'package:latlong2/latlong.dart';
import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';
import 'package:xml/xml.dart';

import '../../domain/models.dart';

class ImportedFeature {
  const ImportedFeature({
    required this.type,
    required this.geometry,
    required this.name,
    this.note = '',
  });

  final FeatureType type;
  final List<LatLng> geometry;
  final String name;
  final String note;
}

class ImportExportService {
  Future<PlatformFile?> pickFile(List<String> extensions) async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: extensions,
      withData: false,
    );
    return result?.files.single;
  }

  MapSourceType sourceTypeFor(String path) {
    final extension = path.split('.').last.toLowerCase();
    return switch (extension) {
      'pdf' => MapSourceType.pdf,
      'tif' || 'tiff' => MapSourceType.geotiff,
      'mbtiles' => MapSourceType.mbtiles,
      'gpkg' => MapSourceType.geopackage,
      _ => MapSourceType.unknown,
    };
  }

  Future<String> copyIntoAppStorage(PlatformFile file) async {
    final sourcePath = file.path;
    if (sourcePath == null) {
      throw StateError(
          'O sistema não forneceu um caminho local para o arquivo.');
    }
    final documents = await getApplicationDocumentsDirectory();
    final mapsDirectory = Directory(path.join(documents.path, 'maps'));
    await mapsDirectory.create(recursive: true);
    final destination = path.join(
      mapsDirectory.path,
      '${DateTime.now().microsecondsSinceEpoch}_${path.basename(file.name)}',
    );
    await File(sourcePath).copy(destination);
    return destination;
  }

  Future<String> copyPhotoIntoAppStorage(XFile file) async {
    final documents = await getApplicationDocumentsDirectory();
    final photosDirectory = Directory(path.join(documents.path, 'photos'));
    await photosDirectory.create(recursive: true);
    final extension =
        path.extension(file.path).isEmpty ? '.jpg' : path.extension(file.path);
    final destination = path.join(
      photosDirectory.path,
      '${DateTime.now().microsecondsSinceEpoch}$extension',
    );
    await File(file.path).copy(destination);
    return destination;
  }

  Future<List<ImportedFeature>> parseFeatures(String filePath) async {
    final extension = filePath.split('.').last.toLowerCase();
    final bytes = await File(filePath).readAsBytes();
    if (extension == 'kmz') {
      final archive = ZipDecoder().decodeBytes(bytes);
      final kmlFile = archive.files.firstWhere(
        (file) => file.name.toLowerCase().endsWith('.kml'),
      );
      return _parseKml(utf8.decode(kmlFile.content as List<int>));
    }
    final content = utf8.decode(bytes);
    if (extension == 'kml') return _parseKml(content);
    if (extension == 'gpx') return _parseGpx(content);
    if (extension == 'geojson' || extension == 'json') {
      return _parseGeoJson(content);
    }
    return const [];
  }

  Future<String?> exportKml({
    required String fileName,
    required List<MapFeature> features,
  }) async {
    final target = await FilePicker.platform.saveFile(
      dialogTitle: 'Exportar camada',
      fileName: fileName.endsWith('.kml') ? fileName : '$fileName.kml',
      type: FileType.custom,
      allowedExtensions: ['kml'],
    );
    if (target == null) return null;
    final document = XmlDocument([
      XmlElement.tag('kml', attributes: [
        XmlAttribute(
          XmlName('xmlns'),
          'http://www.opengis.net/kml/2.2',
        ),
      ], children: [
        XmlElement.tag('Document', children: [
          for (final feature in features) _featureToKml(feature),
        ]),
      ]),
    ]);
    await File(target).writeAsString(document.toXmlString(pretty: true));
    return target;
  }

  XmlElement _featureToKml(MapFeature feature) {
    final coordinates = feature.geometry
        .map((point) => '${point.longitude},${point.latitude},0')
        .join(' ');
    final placemarkChildren = <XmlNode>[
      XmlElement.tag('name', children: [XmlText(feature.name)]),
    ];
    switch (feature.type) {
      case FeatureType.point:
        placemarkChildren.add(XmlElement.tag('Point', children: [
          XmlElement.tag('coordinates', children: [XmlText(coordinates)]),
        ]));
      case FeatureType.line:
      case FeatureType.track:
        placemarkChildren.add(XmlElement.tag('LineString', children: [
          XmlElement.tag('tessellate', children: [XmlText('1')]),
          XmlElement.tag('coordinates', children: [XmlText(coordinates)]),
        ]));
      case FeatureType.polygon:
        placemarkChildren.add(XmlElement.tag('Polygon', children: [
          XmlElement.tag('outerBoundaryIs', children: [
            XmlElement.tag('LinearRing', children: [
              XmlElement.tag('coordinates', children: [XmlText(coordinates)]),
            ]),
          ]),
        ]));
    }
    return XmlElement.tag('Placemark', children: placemarkChildren);
  }

  List<ImportedFeature> _parseKml(String content) {
    final document = XmlDocument.parse(content);
    final features = <ImportedFeature>[];
    for (final placemark in document.findAllElements('Placemark')) {
      final name =
          placemark.getElement('name')?.innerText.trim() ?? 'Importado';
      final point = placemark.findAllElements('Point').firstOrNull;
      final line = placemark.findAllElements('LineString').firstOrNull;
      final polygon = placemark.findAllElements('Polygon').firstOrNull;
      if (point != null) {
        final geometry = _parseCoordinateText(
          point.getElement('coordinates')?.innerText ?? '',
        );
        if (geometry.isNotEmpty) {
          features.add(ImportedFeature(
            type: FeatureType.point,
            geometry: [geometry.first],
            name: name,
          ));
        }
      } else if (line != null) {
        final geometry = _parseCoordinateText(
          line.getElement('coordinates')?.innerText ?? '',
        );
        if (geometry.length > 1) {
          features.add(ImportedFeature(
            type: FeatureType.line,
            geometry: geometry,
            name: name,
          ));
        }
      } else if (polygon != null) {
        final coordinates = polygon.findAllElements('coordinates').firstOrNull;
        final geometry = _parseCoordinateText(coordinates?.innerText ?? '');
        if (geometry.length > 2) {
          features.add(ImportedFeature(
            type: FeatureType.polygon,
            geometry: geometry,
            name: name,
          ));
        }
      }
    }
    return features;
  }

  List<ImportedFeature> _parseGpx(String content) {
    final document = XmlDocument.parse(content);
    final features = <ImportedFeature>[];
    for (final waypoint in document.findAllElements('wpt')) {
      final lat = double.tryParse(waypoint.getAttribute('lat') ?? '');
      final lng = double.tryParse(waypoint.getAttribute('lon') ?? '');
      if (lat != null && lng != null) {
        features.add(ImportedFeature(
          type: FeatureType.point,
          geometry: [LatLng(lat, lng)],
          name: waypoint.getElement('name')?.innerText.trim() ?? 'Waypoint',
        ));
      }
    }
    for (final track in document.findAllElements('trk')) {
      final geometry = track.findAllElements('trkpt').map((point) {
        return LatLng(
          double.parse(point.getAttribute('lat')!),
          double.parse(point.getAttribute('lon')!),
        );
      }).toList();
      if (geometry.length > 1) {
        features.add(ImportedFeature(
          type: FeatureType.track,
          geometry: geometry,
          name: track.getElement('name')?.innerText.trim() ?? 'Trilha',
        ));
      }
    }
    return features;
  }

  List<ImportedFeature> _parseGeoJson(String content) {
    final json = jsonDecode(content) as Map<String, dynamic>;
    final rawFeatures = json['type'] == 'FeatureCollection'
        ? (json['features'] as List<dynamic>)
        : [json];
    return rawFeatures
        .map((raw) => _geoJsonFeature(raw as Map<String, dynamic>))
        .whereType<ImportedFeature>()
        .toList();
  }

  ImportedFeature? _geoJsonFeature(Map<String, dynamic> raw) {
    final geometry = raw['geometry'] as Map<String, dynamic>?;
    if (geometry == null) return null;
    final coordinates = geometry['coordinates'];
    final name =
        ((raw['properties'] as Map<String, dynamic>?)?['name'] ?? 'GeoJSON')
            .toString();
    switch (geometry['type']) {
      case 'Point':
        final point = coordinates as List<dynamic>;
        return ImportedFeature(
          type: FeatureType.point,
          geometry: [
            LatLng((point[1] as num).toDouble(), (point[0] as num).toDouble())
          ],
          name: name,
        );
      case 'LineString':
        return ImportedFeature(
          type: FeatureType.line,
          geometry: _geoJsonCoordinates(coordinates as List<dynamic>),
          name: name,
        );
      case 'Polygon':
        final rings = coordinates as List<dynamic>;
        return ImportedFeature(
          type: FeatureType.polygon,
          geometry: _geoJsonCoordinates(rings.first as List<dynamic>),
          name: name,
        );
      default:
        return null;
    }
  }

  List<LatLng> _geoJsonCoordinates(List<dynamic> coordinates) {
    return coordinates.map((item) {
      final point = item as List<dynamic>;
      return LatLng((point[1] as num).toDouble(), (point[0] as num).toDouble());
    }).toList();
  }

  List<LatLng> _parseCoordinateText(String value) {
    return value
        .trim()
        .split(RegExp(r'\s+'))
        .map((item) => item.split(','))
        .where((parts) => parts.length >= 2)
        .map((parts) {
          final lng = double.tryParse(parts[0]);
          final lat = double.tryParse(parts[1]);
          return lng != null && lat != null ? LatLng(lat, lng) : null;
        })
        .whereType<LatLng>()
        .toList();
  }
}

extension FirstXmlOrNull on Iterable<XmlElement> {
  XmlElement? get firstOrNull => isEmpty ? null : first;
}
