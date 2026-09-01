import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_map_mbtiles/flutter_map_mbtiles.dart';
import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';

import '../../core/location_service.dart';
import '../../domain/map_repository.dart';
import '../../domain/models.dart';
import '../import_export/import_export_service.dart';
import '../layers/feature_list_sheet.dart';
import 'geo_raster_overlay.dart';

class MapViewPage extends StatefulWidget {
  const MapViewPage({required this.map, super.key});

  final MapDocument map;

  @override
  State<MapViewPage> createState() => _MapViewPageState();
}

class _MapViewPageState extends State<MapViewPage> {
  final MapController _mapController = MapController();
  final LocationService _locationService = LocationService();
  final ImportExportService _importExportService = ImportExportService();
  StreamSubscription<Position>? _positionSubscription;
  LatLng? _currentPosition;
  FeatureType? _captureType;
  List<LatLng> _draftGeometry = const [];
  bool _tracking = false;
  List<LatLng> _trackPoints = const [];
  MbTilesTileProvider? _mbTilesProvider;
  GeoRasterOverlay? _geoRasterOverlay;
  String? _tileError;

  @override
  void initState() {
    super.initState();
    _loadOfflineTiles();
    _loadGeoRaster();
  }

  Future<void> _loadOfflineTiles() async {
    if (widget.map.sourceType != MapSourceType.mbtiles) return;
    try {
      final provider =
          MbTilesTileProvider.fromPath(path: widget.map.sourcePath);
      if (!mounted) {
        provider.dispose();
        return;
      }
      setState(() => _mbTilesProvider = provider);
    } catch (error) {
      if (mounted) setState(() => _tileError = error.toString());
    }
  }

  Future<void> _loadGeoRaster() async {
    if (widget.map.sourceType != MapSourceType.geotiff) return;
    try {
      final overlay =
          await GeoRasterService().loadGeoTiff(widget.map.sourcePath);
      if (mounted) setState(() => _geoRasterOverlay = overlay);
    } catch (error) {
      if (mounted) setState(() => _tileError = error.toString());
    }
  }

  @override
  void dispose() {
    _positionSubscription?.cancel();
    _mbTilesProvider?.dispose();
    super.dispose();
  }

  Future<void> _centerOnLocation() async {
    final position = await _locationService.getCurrentPosition();
    if (!mounted) return;
    if (position == null) {
      _message('Não foi possível obter a localização.');
      return;
    }
    final point = LatLng(position.latitude, position.longitude);
    setState(() => _currentPosition = point);
    _mapController.move(point, 16);
  }

  Future<void> _toggleTracking() async {
    if (_tracking) {
      _positionSubscription?.cancel();
      final points = _trackPoints;
      setState(() {
        _tracking = false;
        _trackPoints = const [];
      });
      if (points.length > 1) {
        await context.read<MapRepository>().addImportedFeature(
              type: FeatureType.track,
              geometry: points,
              name: 'Trilha ${DateTime.now().toLocal().toIso8601String()}',
            );
        if (mounted) _message('Trilha salva offline.');
      }
      return;
    }
    setState(() {
      _tracking = true;
      _trackPoints = const [];
    });
    _positionSubscription = _locationService.watchPosition().listen((position) {
      if (!mounted) return;
      final point = LatLng(position.latitude, position.longitude);
      setState(() {
        _currentPosition = point;
        _trackPoints = [..._trackPoints, point];
      });
    });
  }

  Future<void> _importLayer() async {
    final repository = context.read<MapRepository>();
    final file = await _importExportService.pickFile(
      ['kml', 'kmz', 'gpx', 'geojson', 'json'],
    );
    if (!mounted || file?.path == null) return;
    try {
      final imported = await _importExportService.parseFeatures(file!.path!);
      for (final feature in imported) {
        await repository.addImportedFeature(
          type: feature.type,
          geometry: feature.geometry,
          name: feature.name,
          note: feature.note,
        );
      }
      _message('${imported.length} feição(ões) importada(s).');
    } catch (error) {
      _message('Falha ao importar a camada: $error');
    }
  }

  Future<void> _exportLayer() async {
    final repository = context.read<MapRepository>();
    final path = await _importExportService.exportKml(
      fileName: widget.map.name,
      features: repository.features,
    );
    if (mounted && path != null) _message('Camada exportada para $path.');
  }

  Future<void> _addPoint(LatLng point) async {
    final repository = context.read<MapRepository>();
    final feature = await repository.addPoint(point);
    if (!mounted) return;
    setState(() {
      _captureType = null;
      _draftGeometry = const [];
    });
    _message(
        feature == null ? 'Nenhuma camada ativa.' : 'Ponto salvo offline.');
  }

  void _showCaptureMenu() {
    showModalBottomSheet<void>(
      context: context,
      builder: (context) => SafeArea(
        child: Wrap(
          children: [
            const ListTile(
              title: Text('Nova coleta'),
              subtitle: Text('Escolha o tipo de geometria'),
            ),
            ListTile(
              leading: const Icon(Icons.location_on_outlined),
              title: const Text('Ponto'),
              onTap: () => _beginCapture(FeatureType.point),
            ),
            ListTile(
              leading: const Icon(Icons.timeline_outlined),
              title: const Text('Linha ou trilha'),
              onTap: () => _beginCapture(FeatureType.line),
            ),
            ListTile(
              leading: const Icon(Icons.pentagon_outlined),
              title: const Text('Área/polígono'),
              onTap: () => _beginCapture(FeatureType.polygon),
            ),
          ],
        ),
      ),
    );
  }

  void _beginCapture(FeatureType type) {
    Navigator.of(context).pop();
    setState(() {
      _captureType = type;
      _draftGeometry = const [];
    });
  }

  void _captureTap(LatLng point) {
    if (_captureType == FeatureType.point) {
      _addPoint(point);
      return;
    }
    if (_captureType != null) {
      setState(() => _draftGeometry = [..._draftGeometry, point]);
    }
  }

  Future<void> _finishCapture() async {
    final type = _captureType;
    final minimum = type == FeatureType.polygon ? 3 : 2;
    if (type == null || _draftGeometry.length < minimum) {
      _message('Adicione pelo menos $minimum vértices.');
      return;
    }
    final feature = await context.read<MapRepository>().addImportedFeature(
          type: type,
          geometry: _draftGeometry,
          name:
              type == FeatureType.polygon ? 'Área coletada' : 'Linha coletada',
        );
    if (!mounted) return;
    setState(() {
      _captureType = null;
      _draftGeometry = const [];
    });
    _message(
        feature == null ? 'Nenhuma camada ativa.' : 'Geometria salva offline.');
  }

  void _message(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<MapRepository>(
      builder: (context, repository, _) {
        final features = repository.features;
        return Scaffold(
          appBar: AppBar(
            title: Text(
              widget.map.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            actions: [
              IconButton(
                tooltip: 'Importar camada',
                onPressed: _importLayer,
                icon: const Icon(Icons.layers_outlined),
              ),
              IconButton(
                tooltip: 'Exportar KML',
                onPressed: features.isEmpty ? null : _exportLayer,
                icon: const Icon(Icons.ios_share_outlined),
              ),
              IconButton(
                tooltip: 'Camadas e feições',
                onPressed: () => showFeatureListSheet(context),
                icon: const Icon(Icons.list_alt_outlined),
              ),
            ],
          ),
          body: Stack(
            children: [
              FlutterMap(
                options: MapOptions(
                  initialCenter:
                      _currentPosition ?? const LatLng(-15.78, -47.93),
                  initialZoom: 5,
                  onTap: (_, point) => _captureTap(point),
                ),
                mapController: _mapController,
                children: [
                  _tileLayer(),
                  if (_geoRasterOverlay != null)
                    OverlayImageLayer(
                      overlayImages: [
                        OverlayImage(
                          bounds: _geoRasterOverlay!.bounds,
                          imageProvider: MemoryImage(
                            _geoRasterOverlay!.pngBytes,
                          ),
                          opacity: 0.85,
                        ),
                      ],
                    ),
                  PolylineLayer(
                    polylines: [
                      ...features
                          .where((feature) =>
                              feature.type == FeatureType.line ||
                              feature.type == FeatureType.track)
                          .map((feature) => Polyline(
                                points: feature.geometry,
                                color: const Color(0xff1565c0),
                                strokeWidth: 4,
                              )),
                      if (_captureType == FeatureType.line &&
                          _draftGeometry.length > 1)
                        Polyline(
                          points: _draftGeometry,
                          color: const Color(0xffef6c00),
                          strokeWidth: 5,
                        ),
                      if (_tracking && _trackPoints.length > 1)
                        Polyline(
                          points: _trackPoints,
                          color: const Color(0xff2e7d32),
                          strokeWidth: 5,
                        ),
                    ],
                  ),
                  PolygonLayer(
                    polygons: [
                      ...features
                          .where(
                              (feature) => feature.type == FeatureType.polygon)
                          .map((feature) => Polygon(
                                points: feature.geometry,
                                color: const Color(0xff1565c0).withAlpha(51),
                                borderColor: const Color(0xff1565c0),
                                borderStrokeWidth: 2,
                              )),
                      if (_captureType == FeatureType.polygon &&
                          _draftGeometry.length > 2)
                        Polygon(
                          points: _draftGeometry,
                          color: const Color(0xffef6c00).withAlpha(64),
                          borderColor: const Color(0xffef6c00),
                          borderStrokeWidth: 3,
                        ),
                    ],
                  ),
                  MarkerLayer(
                    markers: [
                      ...features
                          .where((feature) => feature.type == FeatureType.point)
                          .where((feature) => feature.geometry.isNotEmpty)
                          .map((feature) => Marker(
                                point: feature.geometry.first,
                                width: 42,
                                height: 42,
                                child: Tooltip(
                                  message: feature.name,
                                  child: const Icon(
                                    Icons.location_on,
                                    size: 38,
                                    color: Color(0xffd32f2f),
                                  ),
                                ),
                              )),
                      if (_currentPosition != null)
                        Marker(
                          point: _currentPosition!,
                          width: 34,
                          height: 34,
                          child: const Icon(
                            Icons.my_location,
                            color: Color(0xff1565c0),
                            size: 30,
                          ),
                        ),
                    ],
                  ),
                  RichAttributionWidget(
                    attributions: [
                      TextSourceAttribution('OpenStreetMap contributors'),
                    ],
                  ),
                ],
              ),
              if (_captureType != null)
                Positioned(
                  top: 16,
                  left: 16,
                  right: 16,
                  child: Card(
                    color: Theme.of(context).colorScheme.primaryContainer,
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Row(
                        children: [
                          const Icon(Icons.touch_app_outlined),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              _captureType == FeatureType.point
                                  ? 'Toque no mapa para salvar um ponto.'
                                  : 'Toque no mapa para adicionar vértices (${_draftGeometry.length}).',
                            ),
                          ),
                          if (_captureType != FeatureType.point)
                            IconButton(
                              tooltip: 'Concluir',
                              onPressed: _finishCapture,
                              icon: const Icon(Icons.check),
                            ),
                          IconButton(
                            tooltip: 'Cancelar',
                            onPressed: () => setState(() {
                              _captureType = null;
                              _draftGeometry = const [];
                            }),
                            icon: const Icon(Icons.close),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              if (_tileError != null)
                Positioned(
                  left: 16,
                  right: 16,
                  bottom: 16,
                  child: Card(
                    color: Theme.of(context).colorScheme.errorContainer,
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Text('Falha ao abrir mapa offline: $_tileError'),
                    ),
                  ),
                ),
            ],
          ),
          floatingActionButton: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              FloatingActionButton.small(
                heroTag: 'tracking',
                onPressed: _toggleTracking,
                backgroundColor:
                    _tracking ? Theme.of(context).colorScheme.primary : null,
                foregroundColor:
                    _tracking ? Theme.of(context).colorScheme.onPrimary : null,
                child: Icon(_tracking ? Icons.gps_fixed : Icons.gps_not_fixed),
              ),
              const SizedBox(height: 10),
              FloatingActionButton.small(
                heroTag: 'location',
                onPressed: _centerOnLocation,
                child: const Icon(Icons.my_location),
              ),
              const SizedBox(height: 10),
              FloatingActionButton.extended(
                heroTag: 'point',
                onPressed: _showCaptureMenu,
                icon: const Icon(Icons.add_location_alt_outlined),
                label: const Text('Coletar'),
              ),
            ],
          ),
        );
      },
    );
  }

  TileLayer _tileLayer() {
    if (_mbTilesProvider != null) {
      return TileLayer(tileProvider: _mbTilesProvider!);
    }
    return TileLayer(
      urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      userAgentPackageName: 'br.com.atlascampo.app',
    );
  }
}
