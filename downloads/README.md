# Downloads

This directory is for large local bootstrap assets that should be fetched on demand and should not be committed to Git.

Examples:

- `downloads/webarena-verified-map/nominatim_volumes.tar`
- `downloads/webarena-verified-map/osrm_routing.tar`
- `downloads/webarena-verified-map/osm_tile_server.tar`
- `downloads/webarena-verified-map/monaco-latest.osm.pbf`

Use the source-specific setup scripts to repopulate this directory when needed, for example:

```bash
./scripts/setup_webarena_map_data.sh downloads/webarena-verified-map full
```

The benchmark runtime uses Docker volumes after extraction, so these archives are local bootstrap artifacts rather than versioned benchmark assets.
