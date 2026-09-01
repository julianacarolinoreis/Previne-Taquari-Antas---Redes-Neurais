import 'sync_models.dart';
import 'sync_queue.dart';
import 'map_repository.dart';

class SyncResult {
  const SyncResult({
    required this.applied,
    required this.conflicts,
    required this.remaining,
  });

  final int applied;
  final int conflicts;
  final int remaining;
}

class SyncCoordinator {
  SyncCoordinator({required this.queue, required this.client});

  final SyncQueueRepository queue;
  final SyncClient client;

  Future<SyncResult> pushPending({
    required String bearerToken,
    required String deviceId,
  }) async {
    final pending = await queue.pending();
    if (pending.isEmpty) {
      return const SyncResult(applied: 0, conflicts: 0, remaining: 0);
    }
    final response = await client.push(
      bearerToken: bearerToken,
      deviceId: deviceId,
      operations: pending.map((item) => item.operation).toList(),
    );
    final results = (response['results'] as List<dynamic>? ?? const []);
    var applied = 0;
    var conflicts = 0;
    for (final item in results) {
      final result = item as Map<String, dynamic>;
      final status = result['status'];
      if (status == 'applied' || status == 'already_applied') {
        await queue.remove(result['operationId'] as String);
        applied++;
      } else if (status == 'conflict') {
        conflicts++;
      }
    }
    return SyncResult(
      applied: applied,
      conflicts: conflicts,
      remaining: await queue.pendingCount(),
    );
  }

  Future<int> pullAndApply({
    required String bearerToken,
    required MapRepository repository,
  }) async {
    final cursor = await queue.cursor();
    final response = await client.pull(
      bearerToken: bearerToken,
      cursor: cursor,
    );
    final changes = (response['changes'] as List<dynamic>? ?? const []);
    for (final rawChange in changes) {
      await repository.applyRemoteChange(
        Map<String, dynamic>.from(rawChange as Map<dynamic, dynamic>),
      );
    }
    final nextCursor = (response['cursor'] as num?)?.toInt() ?? cursor;
    await queue.saveCursor(nextCursor);
    return nextCursor;
  }
}
