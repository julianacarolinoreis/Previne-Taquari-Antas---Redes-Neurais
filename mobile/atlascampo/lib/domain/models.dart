import 'dart:convert';

import 'package:latlong2/latlong.dart';

enum MapSourceType { pdf, geotiff, mbtiles, geopackage, unknown }

enum FeatureType { point, line, polygon, track }

MapSourceType mapSourceTypeFromString(String? value) {
  return MapSourceType.values.firstWhere(
    (item) => item.name == value,
    orElse: () => MapSourceType.unknown,
  );
}

FeatureType featureTypeFromString(String? value) {
  return FeatureType.values.firstWhere(
    (item) => item.name == value,
    orElse: () => FeatureType.point,
  );
}

class MapDocument {
  const MapDocument({
    required this.id,
    required this.name,
    required this.sourcePath,
    required this.sourceType,
    required this.createdAt,
    required this.updatedAt,
    this.isOffline = false,
    this.description = '',
  });

  final String id;
  final String name;
  final String sourcePath;
  final MapSourceType sourceType;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool isOffline;
  final String description;

  Map<String, Object?> toRow() => {
        'id': id,
        'name': name,
        'source_path': sourcePath,
        'source_type': sourceType.name,
        'created_at': createdAt.millisecondsSinceEpoch,
        'updated_at': updatedAt.millisecondsSinceEpoch,
        'is_offline': isOffline ? 1 : 0,
        'description': description,
      };

  factory MapDocument.fromRow(Map<String, Object?> row) {
    return MapDocument(
      id: row['id']! as String,
      name: row['name']! as String,
      sourcePath: row['source_path']! as String,
      sourceType: mapSourceTypeFromString(row['source_type'] as String?),
      createdAt: DateTime.fromMillisecondsSinceEpoch(row['created_at']! as int),
      updatedAt: DateTime.fromMillisecondsSinceEpoch(row['updated_at']! as int),
      isOffline: (row['is_offline'] as int? ?? 0) == 1,
      description: row['description'] as String? ?? '',
    );
  }
}

class MapLayer {
  const MapLayer({
    required this.id,
    required this.mapId,
    required this.name,
    required this.colorValue,
    required this.visible,
  });

  final String id;
  final String mapId;
  final String name;
  final int colorValue;
  final bool visible;

  Map<String, Object?> toRow() => {
        'id': id,
        'map_id': mapId,
        'name': name,
        'color_value': colorValue,
        'visible': visible ? 1 : 0,
      };

  factory MapLayer.fromRow(Map<String, Object?> row) => MapLayer(
        id: row['id']! as String,
        mapId: row['map_id']! as String,
        name: row['name']! as String,
        colorValue: row['color_value']! as int,
        visible: (row['visible'] as int? ?? 1) == 1,
      );
}

class MapFeature {
  const MapFeature({
    required this.id,
    required this.mapId,
    required this.layerId,
    required this.type,
    required this.geometry,
    required this.createdAt,
    required this.updatedAt,
    this.revision = 0,
    this.name = '',
    this.note = '',
    this.photoPath,
    this.attributes = const <String, String>{},
  });

  final String id;
  final String mapId;
  final String layerId;
  final FeatureType type;
  final List<LatLng> geometry;
  final DateTime createdAt;
  final DateTime updatedAt;
  final int revision;
  final String name;
  final String note;
  final String? photoPath;
  final Map<String, String> attributes;

  MapFeature copyWith({
    String? name,
    String? note,
    String? photoPath,
    Map<String, String>? attributes,
    int? revision,
  }) {
    return MapFeature(
      id: id,
      mapId: mapId,
      layerId: layerId,
      type: type,
      geometry: geometry,
      createdAt: createdAt,
      updatedAt: DateTime.now(),
      revision: revision ?? this.revision,
      name: name ?? this.name,
      note: note ?? this.note,
      photoPath: photoPath ?? this.photoPath,
      attributes: attributes ?? this.attributes,
    );
  }

  Map<String, Object?> toRow() => {
        'id': id,
        'map_id': mapId,
        'layer_id': layerId,
        'type': type.name,
        'geometry': jsonEncode(geometry
            .map((point) => <String, double>{
                  'lat': point.latitude,
                  'lng': point.longitude,
                })
            .toList()),
        'created_at': createdAt.millisecondsSinceEpoch,
        'updated_at': updatedAt.millisecondsSinceEpoch,
        'revision': revision,
        'name': name,
        'note': note,
        'photo_path': photoPath,
        'attributes': jsonEncode(attributes),
      };

  factory MapFeature.fromRow(Map<String, Object?> row) {
    final rawGeometry = jsonDecode(row['geometry']! as String) as List<dynamic>;
    final attributes = jsonDecode(row['attributes'] as String? ?? '{}');
    return MapFeature(
      id: row['id']! as String,
      mapId: row['map_id']! as String,
      layerId: row['layer_id']! as String,
      type: featureTypeFromString(row['type'] as String?),
      geometry: rawGeometry
          .map((item) => LatLng(
                (item['lat'] as num).toDouble(),
                (item['lng'] as num).toDouble(),
              ))
          .toList(),
      createdAt: DateTime.fromMillisecondsSinceEpoch(row['created_at']! as int),
      updatedAt: DateTime.fromMillisecondsSinceEpoch(row['updated_at']! as int),
      revision: row['revision'] as int? ?? 0,
      name: row['name'] as String? ?? '',
      note: row['note'] as String? ?? '',
      photoPath: row['photo_path'] as String?,
      attributes: Map<String, String>.from(attributes as Map<dynamic, dynamic>),
    );
  }

  Map<String, Object?> toSyncPayload() {
    final coordinates = geometry
        .map((point) => <double>[point.longitude, point.latitude])
        .toList();
    final geometryType = switch (type) {
      FeatureType.point => 'Point',
      FeatureType.line || FeatureType.track => 'LineString',
      FeatureType.polygon => 'Polygon',
    };
    final geometryCoordinates = type == FeatureType.point
        ? coordinates.first
        : type == FeatureType.polygon
            ? [
                [
                  ...coordinates,
                  if (coordinates.isNotEmpty &&
                      coordinates.first != coordinates.last)
                    coordinates.first,
                ],
              ]
            : coordinates;
    return {
      'mapId': mapId,
      'layerId': layerId,
      'projectId': null,
      'geometry': {
        'type': geometryType,
        'coordinates': geometryCoordinates,
      },
      'properties': {
        'name': name,
        'note': note,
        'attributes': attributes,
        'photoPath': photoPath,
      },
    };
  }

  factory MapFeature.fromSyncPayload({
    required String id,
    required int revision,
    required Map<String, dynamic> payload,
  }) {
    final rawGeometry = payload['geometry'] as Map<String, dynamic>;
    final rawCoordinates = rawGeometry['coordinates'];
    final type = switch (rawGeometry['type']) {
      'Point' => FeatureType.point,
      'LineString' => FeatureType.line,
      'Polygon' => FeatureType.polygon,
      _ => throw FormatException('Tipo de geometria não suportado.'),
    };
    final geometry = switch (type) {
      FeatureType.point => [_syncPoint(rawCoordinates as List<dynamic>)],
      FeatureType.line => _syncPoints(rawCoordinates as List<dynamic>),
      FeatureType.track => _syncPoints(rawCoordinates as List<dynamic>),
      FeatureType.polygon => _syncPoints(
          (rawCoordinates as List<dynamic>).first as List<dynamic>,
        ),
    };
    final properties = Map<String, dynamic>.from(
      payload['properties'] as Map<dynamic, dynamic>? ?? const {},
    );
    final rawAttributes = properties['attributes'];
    return MapFeature(
      id: id,
      mapId: payload['mapId'] as String? ?? '',
      layerId: payload['layerId'] as String,
      type: type,
      geometry: geometry,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      revision: revision,
      name: properties['name'] as String? ?? 'Sincronizado',
      note: properties['note'] as String? ?? '',
      photoPath: properties['photoPath'] as String?,
      attributes: Map<String, String>.from(
        rawAttributes as Map<dynamic, dynamic>? ?? const {},
      ),
    );
  }

  static LatLng _syncPoint(List<dynamic> point) {
    return LatLng(
      (point[1] as num).toDouble(),
      (point[0] as num).toDouble(),
    );
  }

  static List<LatLng> _syncPoints(List<dynamic> points) {
    return points.map((point) => _syncPoint(point as List<dynamic>)).toList();
  }
}
