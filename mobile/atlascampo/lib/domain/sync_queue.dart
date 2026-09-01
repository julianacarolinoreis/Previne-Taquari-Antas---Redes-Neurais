import 'dart:convert';

import 'package:uuid/uuid.dart';
import 'package:sqflite/sqflite.dart';

import '../core/local_database.dart';
import 'sync_models.dart';

class QueuedSyncOperation {
  const QueuedSyncOperation({
    required this.operation,
    required this.createdAt,
  });

  final SyncOperation operation;
  final DateTime createdAt;

  factory QueuedSyncOperation.fromRow(Map<String, Object?> row) {
    return QueuedSyncOperation(
      operation: SyncOperation(
        operationId: row['operation_id']! as String,
        entity: row['entity']! as String,
        entityId: row['entity_id']! as String,
        action: row['action']! as String,
        baseRevision: row['base_revision']! as int,
        payload: Map<String, Object?>.from(
          jsonDecode(row['payload']! as String) as Map<dynamic, dynamic>,
        ),
      ),
      createdAt: DateTime.fromMillisecondsSinceEpoch(
        row['created_at']! as int,
      ),
    );
  }
}

class SyncQueueRepository {
  SyncQueueRepository(this._localDatabase);

  final LocalDatabase _localDatabase;
  final Uuid _uuid = const Uuid();

  Future<void> enqueue({
    required String entity,
    required String entityId,
    required String action,
    required int baseRevision,
    required Map<String, Object?> payload,
  }) async {
    final operation = SyncOperation(
      operationId: _uuid.v4(),
      entity: entity,
      entityId: entityId,
      action: action,
      baseRevision: baseRevision,
      payload: payload,
    );
    final db = await _localDatabase.database;
    await db.delete(
      'sync_queue',
      where: 'entity = ? AND entity_id = ?',
      whereArgs: [entity, entityId],
    );
    await db.insert('sync_queue', {
      'operation_id': operation.operationId,
      'entity': operation.entity,
      'entity_id': operation.entityId,
      'action': operation.action,
      'base_revision': operation.baseRevision,
      'payload': jsonEncode(operation.payload),
      'created_at': DateTime.now().millisecondsSinceEpoch,
    });
  }

  Future<List<QueuedSyncOperation>> pending({int limit = 200}) async {
    final db = await _localDatabase.database;
    final rows = await db.query(
      'sync_queue',
      orderBy: 'created_at ASC',
      limit: limit,
    );
    return rows.map(QueuedSyncOperation.fromRow).toList();
  }

  Future<void> remove(String operationId) async {
    final db = await _localDatabase.database;
    await db.delete(
      'sync_queue',
      where: 'operation_id = ?',
      whereArgs: [operationId],
    );
  }

  Future<int> pendingCount() async {
    final db = await _localDatabase.database;
    final rows = await db.rawQuery('SELECT COUNT(*) AS count FROM sync_queue');
    return (rows.first['count'] as int?) ?? 0;
  }

  Future<int> cursor() async {
    final db = await _localDatabase.database;
    final rows = await db.query(
      'sync_state',
      where: 'key = ?',
      whereArgs: ['pull_cursor'],
      limit: 1,
    );
    return int.tryParse(rows.firstOrNull?['value'] as String? ?? '') ?? 0;
  }

  Future<void> saveCursor(int cursor) async {
    final db = await _localDatabase.database;
    await db.insert(
      'sync_state',
      {'key': 'pull_cursor', 'value': '$cursor'},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }
}

extension SyncRowFirstOrNull on List<Map<String, Object?>> {
  Map<String, Object?>? get firstOrNull => isEmpty ? null : first;
}
