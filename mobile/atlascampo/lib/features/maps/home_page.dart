import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../domain/map_repository.dart';
import '../../domain/models.dart';
import '../import_export/import_export_service.dart';
import 'map_view_page.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  Future<void> _importMap(BuildContext context) async {
    final file = await ImportExportService().pickFile(
      ['pdf', 'tif', 'tiff', 'mbtiles', 'gpkg'],
    );
    if (!context.mounted || file?.path == null) return;
    final repository = context.read<MapRepository>();
    final storedPath = await ImportExportService().copyIntoAppStorage(file!);
    if (!context.mounted) return;
    await repository.importMap(
      name: file.name,
      sourcePath: storedPath,
      sourceType: ImportExportService().sourceTypeFor(file.name),
    );
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${file.name} adicionado à biblioteca.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<MapRepository>(
      builder: (context, repository, _) {
        return Scaffold(
          appBar: AppBar(
            title: const Text('AtlasCampo'),
            actions: [
              IconButton(
                tooltip: 'Importar mapa',
                onPressed: () => _importMap(context),
                icon: const Icon(Icons.file_open_outlined),
              ),
              IconButton(
                tooltip: 'Configurações',
                onPressed: () => _showSettings(context),
                icon: const Icon(Icons.settings_outlined),
              ),
            ],
          ),
          body: repository.isLoading
              ? const Center(child: CircularProgressIndicator())
              : repository.maps.isEmpty
                  ? _EmptyLibrary(onImport: () => _importMap(context))
                  : ListView.separated(
                      padding: const EdgeInsets.all(16),
                      itemCount: repository.maps.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 10),
                      itemBuilder: (context, index) {
                        final map = repository.maps[index];
                        return _MapCard(
                          map: map,
                          onOpen: () async {
                            await repository.selectMap(map);
                            if (context.mounted) {
                              Navigator.of(context).push(
                                MaterialPageRoute<void>(
                                  builder: (_) => MapViewPage(map: map),
                                ),
                              );
                            }
                          },
                        );
                      },
                    ),
          floatingActionButton: repository.maps.isEmpty
              ? null
              : FloatingActionButton.extended(
                  onPressed: () => _importMap(context),
                  icon: const Icon(Icons.add),
                  label: const Text('Importar mapa'),
                ),
        );
      },
    );
  }

  void _showSettings(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: const [
            ListTile(
              leading: Icon(Icons.cloud_off_outlined),
              title: Text('Modo offline primeiro'),
              subtitle: Text('Os registros ficam salvos no dispositivo.'),
            ),
            ListTile(
              leading: Icon(Icons.info_outline),
              title: Text('AtlasCampo 0.1.0'),
              subtitle: Text('Mapas e dados de campo'),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyLibrary extends StatelessWidget {
  const _EmptyLibrary({required this.onImport});

  final VoidCallback onImport;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.map_outlined,
              size: 80,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 20),
            Text(
              'Sua biblioteca está vazia',
              style: Theme.of(context).textTheme.headlineSmall,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            const Text(
              'Importe um mapa georreferenciado para começar a trabalhar offline.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              onPressed: onImport,
              icon: const Icon(Icons.file_open_outlined),
              label: const Text('Importar mapa'),
            ),
          ],
        ),
      ),
    );
  }
}

class _MapCard extends StatelessWidget {
  const _MapCard({required this.map, required this.onOpen});

  final MapDocument map;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpen,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              CircleAvatar(
                radius: 26,
                backgroundColor: Theme.of(context).colorScheme.primaryContainer,
                child: Icon(
                  _iconFor(map.sourceType),
                  color: Theme.of(context).colorScheme.onPrimaryContainer,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      map.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${map.sourceType.name.toUpperCase()} · ${map.isOffline ? 'offline' : 'online'}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }

  IconData _iconFor(MapSourceType type) {
    return switch (type) {
      MapSourceType.pdf => Icons.picture_as_pdf_outlined,
      MapSourceType.geotiff => Icons.image_outlined,
      MapSourceType.mbtiles => Icons.grid_on_outlined,
      MapSourceType.geopackage => Icons.layers_outlined,
      MapSourceType.unknown => Icons.map_outlined,
    };
  }
}
