import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/local_database.dart';
import 'domain/map_repository.dart';
import 'features/maps/home_page.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final repository = MapRepository(LocalDatabase());
  await repository.initialize();
  runApp(
    ChangeNotifierProvider.value(
      value: repository,
      child: const AtlasCampoApp(),
    ),
  );
}

class AtlasCampoApp extends StatelessWidget {
  const AtlasCampoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AtlasCampo',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff1565c0)),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}
