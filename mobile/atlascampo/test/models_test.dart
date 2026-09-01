import 'package:flutter_test/flutter_test.dart';
import 'package:latlong2/latlong.dart';

import 'package:atlascampo/domain/models.dart';

void main() {
  test('MapFeature preserva geometria e atributos no formato do banco', () {
    final original = MapFeature(
      id: 'feature-1',
      mapId: 'map-1',
      layerId: 'layer-1',
      type: FeatureType.line,
      geometry: const [
        LatLng(-29.98, -51.2),
        LatLng(-29.99, -51.21),
      ],
      createdAt: DateTime.fromMillisecondsSinceEpoch(1),
      updatedAt: DateTime.fromMillisecondsSinceEpoch(2),
      name: 'Linha de teste',
      attributes: const {'classe': 'ponte'},
    );

    final restored = MapFeature.fromRow(original.toRow());

    expect(restored.id, original.id);
    expect(restored.type, FeatureType.line);
    expect(restored.geometry, hasLength(2));
    expect(restored.geometry.first.latitude, -29.98);
    expect(restored.attributes['classe'], 'ponte');
  });

  test('MapFeature usa GeoJSON compatível com a sincronização', () {
    final feature = MapFeature(
      id: 'feature-2',
      mapId: 'map-1',
      layerId: 'layer-1',
      type: FeatureType.polygon,
      geometry: const [
        LatLng(-29.98, -51.2),
        LatLng(-29.98, -51.1),
        LatLng(-29.90, -51.1),
      ],
      createdAt: DateTime.fromMillisecondsSinceEpoch(1),
      updatedAt: DateTime.fromMillisecondsSinceEpoch(2),
      name: 'Área',
    );

    final restored = MapFeature.fromSyncPayload(
      id: feature.id,
      revision: 4,
      payload: Map<String, dynamic>.from(feature.toSyncPayload()),
    );

    expect(restored.type, FeatureType.polygon);
    expect(restored.revision, 4);
    expect(restored.geometry, hasLength(4));
    expect(restored.geometry.last, restored.geometry.first);
  });
}
