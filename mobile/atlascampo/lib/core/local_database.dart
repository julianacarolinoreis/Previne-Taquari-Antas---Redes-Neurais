import 'package:path/path.dart' as path;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

class LocalDatabase {
  Database? _database;

  Future<Database> get database async {
    if (_database != null) return _database!;
    final directory = await getApplicationDocumentsDirectory();
    final databasePath = path.join(directory.path, 'atlascampo.db');
    _database = await openDatabase(
      databasePath,
      version: 3,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE maps (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_type TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            is_offline INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT ''
          )
        ''');
        await db.execute('''
          CREATE TABLE layers (
            id TEXT PRIMARY KEY,
            map_id TEXT NOT NULL,
            name TEXT NOT NULL,
            color_value INTEGER NOT NULL,
            visible INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (map_id) REFERENCES maps(id) ON DELETE CASCADE
          )
        ''');
        await db.execute('''
          CREATE TABLE features (
            id TEXT PRIMARY KEY,
            map_id TEXT NOT NULL,
            layer_id TEXT NOT NULL,
            type TEXT NOT NULL,
            geometry TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            photo_path TEXT,
            attributes TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (map_id) REFERENCES maps(id) ON DELETE CASCADE,
            FOREIGN KEY (layer_id) REFERENCES layers(id) ON DELETE CASCADE
          )
        ''');
        await db.execute(
          'CREATE INDEX features_map_id_idx ON features(map_id)',
        );
        await _createSyncTables(db);
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          await _createSyncTables(db);
        }
        if (oldVersion < 3) {
          await db.execute(
            'ALTER TABLE features ADD COLUMN revision INTEGER NOT NULL DEFAULT 0',
          );
        }
      },
      onConfigure: (db) async {
        await db.execute('PRAGMA foreign_keys = ON');
      },
    );
    return _database!;
  }

  Future<void> _createSyncTables(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS sync_queue (
        operation_id TEXT PRIMARY KEY,
        entity TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        base_revision INTEGER NOT NULL,
        payload TEXT NOT NULL,
        created_at INTEGER NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS sync_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    ''');
  }
}
