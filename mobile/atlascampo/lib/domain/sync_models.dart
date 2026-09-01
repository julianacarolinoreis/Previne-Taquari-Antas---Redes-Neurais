import 'dart:convert';

import 'package:http/http.dart' as http;

class SyncOperation {
  const SyncOperation({
    required this.operationId,
    required this.entity,
    required this.entityId,
    required this.action,
    required this.baseRevision,
    required this.payload,
  });

  final String operationId;
  final String entity;
  final String entityId;
  final String action;
  final int baseRevision;
  final Map<String, Object?> payload;

  Map<String, Object?> toJson() => {
        'operationId': operationId,
        'entity': entity,
        'entityId': entityId,
        'action': action,
        'baseRevision': baseRevision,
        'payload': payload,
      };
}

class SyncClient {
  SyncClient({required this.baseUrl, http.Client? httpClient})
      : httpClient = httpClient ?? http.Client();

  final Uri baseUrl;
  final http.Client httpClient;

  Future<Map<String, dynamic>> push({
    required String bearerToken,
    required String deviceId,
    required List<SyncOperation> operations,
  }) async {
    final response = await httpClient.post(
      baseUrl.resolve('/v1/sync/push'),
      headers: {
        'Authorization': 'Bearer $bearerToken',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({
        'deviceId': deviceId,
        'operations': operations.map((item) => item.toJson()).toList(),
      }),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('Falha na sincronização (${response.statusCode}).');
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> pull({
    required String bearerToken,
    required int cursor,
  }) async {
    final response = await httpClient.get(
      baseUrl.resolve('/v1/sync/pull?cursor=$cursor'),
      headers: {'Authorization': 'Bearer $bearerToken'},
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError('Falha ao baixar alterações (${response.statusCode}).');
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }
}
