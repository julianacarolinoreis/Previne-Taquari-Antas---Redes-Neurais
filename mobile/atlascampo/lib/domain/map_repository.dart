import 'package:flutter/foundation.dart';
import 'package:latlong2/latlong.dart';
import 'package:sqflite/sqflite.dart';
import 'package:uuid/uuid.dart';

import '../core/local_database.dart';
import 'models.dart';
import 'sync_queue.dart';

class MapRepository extends ChangeNotifier {
  MapRepository(this._localDatabase);

  final LocalDatabase _localDatabase;
  final Uuid _uuid = const Uuid();
  late final SyncQueueRepository _syncQueue =
      SyncQueueRepository(_localDatabase);

  List<MapDocument> maps = const [];
  MapDocument? selectedMap;
  List<MapLayer> layers = const [];
  List<MapFeature> features = const [];
  bool isLoading = true;
  String? errorMessage;

  Future<void> initialize() async {
    isLoading = true;
    notifyListeners();
    try {
      final db = await _localDatabase.database;
      final rows = await db.query('maps', orderBy: 'updated_at DESC');
      maps = rows.map(MapDocument.fromRow).toList();
      if (maps.isNotEmpty) await selectMap(maps.first);
    } catch (error) {
      errorMessage = 'Não foi possível abrir os mapas: $error';
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  Future<void> selectMap(MapDocument map) async {
    final db = await _localDatabase.database;
    final layerRows = await db.query(
      'layers',
      where: 'map_id = ?',
      whereArgs: [map.id],
      orderBy: 'name ASC',
    );
    final featureRows = await db.query(
      'features',
      where: 'map_id = ?',
      whereArgs: [map.id],
      orderBy: 'created_at ASC',
    );
    selectedMap = map;
    layers = layerRows.map(MapLayer.fromRow).toList();
    features = featureRows.map(MapFeature.fromRow).toList();
    notifyListeners();
  }

  Future<MapDocument> importMap({
    required String name,
    required String sourcePath,
    required MapSourceType sourceType,
  }) async {
    final now = DateTime.now();
    final map = MapDocument(
      id: _uuid.v4(),
      name: name,
      sourcePath: sourcePath,
      sourceType: sourceType,
      createdAt: now,
      updatedAt: now,
      isOffline: true,
    );
    final layer = MapLayer(
      id: _uuid.v4(),
      mapId: map.id,
      name: 'Coleta de campo',
      colorValue: 0xff1565c0,
      visible: true,
    );
    final db = await _localDatabase.database;
    await db.transaction((transaction) async {
      await transaction.insert('maps', map.toRow());
      await transaction.insert('layers', layer.toRow());
    });
    maps = [map, ...maps];
    await selectMap(map);
    return map;
  }

  Future<MapFeature?> addPoint(LatLng position, {String name = ''}) async {
    final map = selectedMap;
    final layer = layers.where((item) => item.visible).firstOrNull;
    if (map == null || layer == null) return null;
    final now = DateTime.now();
    final feature = MapFeature(
      id: _uuid.v4(),
      mapId: map.id,
      layerId: layer.id,
      type: FeatureType.point,
      geometry: [position],
      createdAt: now,
      updatedAt: now,
      name: name.isEmpty ? 'Ponto ${features.length + 1}' : name,
    );
    final db = await _localDatabase.database;
    await db.insert('features', feature.toRow());
    await _syncQueue.enqueue(
      entity: 'feature',
      entityId: feature.id,
      action: 'upsert',
      baseRevision: feature.revision,
      payload: feature.toSyncPayload(),
    );
    features = [...features, feature];
    notifyListeners();
    return feature;
  }

  Future<MapFeature?> addImportedFeature({
    required FeatureType type,
    required List<LatLng> geometry,
    required String name,
    String note = '',
  }) async {
    final map = selectedMap;
    final layer = layers.where((item) => item.visible).firstOrNull;
    if (map == null || layer == null || geometry.isEmpty) return null;
    final now = DateTime.now();
    final feature = MapFeature(
      id: _uuid.v4(),
      mapId: map.id,
      layerId: layer.id,
      type: type,
      geometry: geometry,
      createdAt: now,
      updatedAt: now,
      name: name,
      note: note,
    );
    final db = await _localDatabase.database;
    await db.insert('features', feature.toRow());
    await _syncQueue.enqueue(
      entity: 'feature',
      entityId: feature.id,
      action: 'upsert',
      baseRevision: feature.revision,
      payload: feature.toSyncPayload(),
    );
    features = [...features, feature];
    notifyListeners();
    return feature;
  }

  Future<void> updateFeature(MapFeature feature) async {
    final db = await _localDatabase.database;
    final updatedFeature = feature.copyWith(revision: feature.revision + 1);
    await db.update(
      'features',
      updatedFeature.toRow(),
      where: 'id = ?',
      whereArgs: [updatedFeature.id],
    );
    features = features
        .map((item) => item.id == updatedFeature.id ? updatedFeature : item)
        .toList();
    await _syncQueue.enqueue(
      entity: 'feature',
      entityId: updatedFeature.id,
      action: 'upsert',
      baseRevision: feature.revision,
      payload: updatedFeature.toSyncPayload(),
    );
    notifyListeners();
  }

  Future<void> deleteFeature(String featureId) async {
    final db = await _localDatabase.database;
    final feature = features.where((item) => item.id == featureId).firstOrNull;
    await db.delete('features', where: 'id = ?', whereArgs: [featureId]);
    if (feature != null) {
      await _syncQueue.enqueue(
        entity: 'feature',
        entityId: feature.id,
        action: 'delete',
        baseRevision: feature.revision,
        payload: const {},
      );
    }
    features = features.where((item) => item.id != featureId).toList();
    notifyListeners();
  }

  Future<void> applyRemoteChange(Map<String, dynamic> change) async {
    if (change['entity'] != 'feature') return;
    final id = change['entityId'] as String;
    final revision = (change['revision'] as num).toInt();
    final payload = Map<String, dynamic>.from(
      change['payload'] as Map<dynamic, dynamic>? ?? const {},
    );
    final db = await _localDatabase.database;
    if (payload['deleted'] == true) {
      await db.delete('features', where: 'id = ?', whereArgs: [id]);
      features = features.where((item) => item.id != id).toList();
    } else {
      final remote = MapFeature.fromSyncPayload(
        id: id,
        revision: revision,
        payload: payload,
      );
      await db.insert(
        'features',
        remote.toRow(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
      features = [
        ...features.where((item) => item.id != id),
        if (selectedMap?.id == remote.mapId) remote,
      ];
    }
    notifyListeners();
  }
}

extension FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
