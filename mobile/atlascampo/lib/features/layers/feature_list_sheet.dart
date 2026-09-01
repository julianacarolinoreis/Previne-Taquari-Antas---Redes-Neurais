import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../../domain/map_repository.dart';
import '../../domain/models.dart';
import '../import_export/import_export_service.dart';
import '../maps/geometry_metrics.dart';

Future<void> showFeatureListSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (_) => const _FeatureListSheet(),
  );
}

class _FeatureListSheet extends StatelessWidget {
  const _FeatureListSheet();

  Future<void> _edit(BuildContext context, MapFeature feature) async {
    final nameController = TextEditingController(text: feature.name);
    final noteController = TextEditingController(text: feature.note);
    final result = await showDialog<Map<String, String>>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Editar feição'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              decoration: const InputDecoration(labelText: 'Nome'),
            ),
            TextField(
              controller: noteController,
              decoration: const InputDecoration(labelText: 'Nota'),
              maxLines: 3,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, {
              'name': nameController.text.trim(),
              'note': noteController.text.trim(),
            }),
            child: const Text('Salvar'),
          ),
        ],
      ),
    );
    nameController.dispose();
    noteController.dispose();
    if (result == null || !context.mounted) return;
    await context.read<MapRepository>().updateFeature(
          feature.copyWith(
            name: result['name'],
            note: result['note'],
          ),
        );
  }

  Future<void> _attachPhoto(BuildContext context, MapFeature feature) async {
    final photo = await ImagePicker().pickImage(
      source: ImageSource.camera,
      imageQuality: 85,
    );
    if (photo == null || !context.mounted) return;
    final path = await ImportExportService().copyPhotoIntoAppStorage(photo);
    if (!context.mounted) return;
    await context.read<MapRepository>().updateFeature(
          feature.copyWith(photoPath: path),
        );
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<MapRepository>(
      builder: (context, repository, _) {
        final features = repository.features;
        return SafeArea(
          child: SizedBox(
            height: MediaQuery.sizeOf(context).height * 0.65,
            child: Column(
              children: [
                const ListTile(
                  leading: Icon(Icons.layers_outlined),
                  title: Text('Camadas e feições'),
                ),
                const Divider(height: 1),
                Expanded(
                  child: features.isEmpty
                      ? const Center(child: Text('Nenhuma feição coletada.'))
                      : ListView.builder(
                          itemCount: features.length,
                          itemBuilder: (context, index) {
                            final feature = features[index];
                            return ListTile(
                              leading: Icon(_iconFor(feature.type)),
                              title: Text(feature.name),
                              subtitle: Text(
                                _subtitle(feature),
                              ),
                              trailing: Wrap(
                                children: [
                                  IconButton(
                                    tooltip: 'Adicionar foto',
                                    onPressed: () =>
                                        _attachPhoto(context, feature),
                                    icon: Icon(
                                      feature.photoPath == null
                                          ? Icons.photo_camera_outlined
                                          : Icons.photo_camera,
                                    ),
                                  ),
                                  IconButton(
                                    tooltip: 'Editar',
                                    onPressed: () => _edit(context, feature),
                                    icon: const Icon(Icons.edit_outlined),
                                  ),
                                  IconButton(
                                    tooltip: 'Excluir',
                                    onPressed: () =>
                                        repository.deleteFeature(feature.id),
                                    icon: const Icon(Icons.delete_outline),
                                  ),
                                ],
                              ),
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  IconData _iconFor(FeatureType type) {
    return switch (type) {
      FeatureType.point => Icons.location_on_outlined,
      FeatureType.line => Icons.timeline_outlined,
      FeatureType.polygon => Icons.pentagon_outlined,
      FeatureType.track => Icons.route_outlined,
    };
  }

  String _subtitle(MapFeature feature) {
    final vertexText = '${feature.geometry.length} vértice(s)';
    if (feature.type == FeatureType.polygon) {
      return '${feature.type.name} · ${_formatArea(polygonAreaSquareMeters(feature.geometry))}';
    }
    if (feature.type == FeatureType.line || feature.type == FeatureType.track) {
      return '${feature.type.name} · ${_formatDistance(geometryLengthMeters(feature.geometry))}';
    }
    return '${feature.type.name} · $vertexText';
  }

  String _formatDistance(double meters) {
    return meters >= 1000
        ? '${(meters / 1000).toStringAsFixed(2)} km'
        : '${meters.toStringAsFixed(1)} m';
  }

  String _formatArea(double squareMeters) {
    return squareMeters >= 10000
        ? '${(squareMeters / 10000).toStringAsFixed(2)} ha'
        : '${squareMeters.toStringAsFixed(1)} m²';
  }
}
