"""Static checks on grafana/dashboard.json against the InfluxDB schema."""

import json
import os

import pytest

from scripts import grafana_import

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DASHBOARD_PATH = os.path.join(ROOT, 'grafana', 'dashboard.json')

# Fields per measurement, as listed in the InfluxDB schema table of SPEC.md.
SCHEMA_FIELDS = {
    'sensor_readings': {'temperature', 'humidity', 'vibration'},
    'sensor_readings_1m': {'temperature', 'humidity', 'vibration', 'vibration_max'},
    'alerts': {'value', 'limit', 'message'},
}
SCHEMA_TAGS = {
    'sensor_readings': {'gateway', 'zone', 'sensor'},
    'sensor_readings_1m': {'gateway', 'zone', 'sensor'},
    'alerts': {'zone', 'sensor', 'metric', 'kind', 'state'},
}


@pytest.fixture(scope='module')
def dashboard():
    with open(DASHBOARD_PATH) as handle:
        return json.load(handle)


def all_panels(dashboard):
    panels = []
    for row in dashboard['rows']:
        panels.extend(row['panels'])
    return panels


def all_targets(dashboard):
    return [(panel, target) for panel in all_panels(dashboard) for target in panel['targets']]


def test_dashboard_metadata(dashboard):
    assert dashboard['title'] == 'Industrial IoT Floor'
    assert dashboard['schemaVersion'] == 14
    assert 'uid' not in dashboard
    assert dashboard.get('id') is None


def test_every_target_uses_a_schema_measurement(dashboard):
    targets = all_targets(dashboard)
    assert targets
    for panel, target in targets:
        assert target['measurement'] in SCHEMA_FIELDS, panel['title']


def test_every_selected_field_exists_in_schema(dashboard):
    for panel, target in all_targets(dashboard):
        fields = SCHEMA_FIELDS[target['measurement']]
        for select in target['select']:
            selected = [part['params'][0] for part in select if part['type'] == 'field']
            assert len(selected) == 1, panel['title']
            assert selected[0] in fields, (panel['title'], selected[0])


def test_every_group_by_and_filter_tag_exists_in_schema(dashboard):
    for panel, target in all_targets(dashboard):
        tags = SCHEMA_TAGS[target['measurement']]
        for group in target.get('groupBy', []):
            if group['type'] == 'tag':
                assert group['params'][0] in tags, panel['title']
        for condition in target.get('tags', []):
            assert condition['key'] in tags, panel['title']


def test_rollup_panel_reads_rollup_retention_policy(dashboard):
    rollup = [(p, t) for p, t in all_targets(dashboard)
              if t['measurement'] == 'sensor_readings_1m']
    assert rollup
    for panel, target in rollup:
        assert target['policy'] == 'rollup'
    assert any(panel['title'] == '1m rollup' for panel, _ in rollup)


def test_metric_graphs_group_by_sensor_and_interval(dashboard):
    graphs = {}
    for panel, target in all_targets(dashboard):
        if panel['type'] == 'graph' and target['measurement'] == 'sensor_readings':
            field = target['select'][0][0]['params'][0]
            graphs[field] = target
    assert set(graphs) == {'temperature', 'humidity', 'vibration'}
    for target in graphs.values():
        group_by = [(g['type'], g['params'][0]) for g in target['groupBy']
                    if g['type'] in ('time', 'tag')]
        assert ('time', '$__interval') in group_by
        assert ('tag', 'sensor') in group_by


def test_alerts_table_panel(dashboard):
    tables = [p for p in all_panels(dashboard) if p['type'] == 'table']
    assert tables
    for table in tables:
        for target in table['targets']:
            assert target['measurement'] == 'alerts'
            assert target['resultFormat'] == 'table'


def test_zone_template_variable(dashboard):
    variables = {var['name']: var for var in dashboard['templating']['list']}
    assert 'zone' in variables
    zone = variables['zone']
    assert zone['type'] == 'query'
    assert zone['query'] == 'SHOW TAG VALUES FROM sensor_readings WITH KEY = "zone"'
    assert zone['datasource'] == grafana_import.DEFAULT_DATASOURCE


def test_every_panel_uses_import_script_default_datasource(dashboard):
    default = grafana_import.build_parser().parse_args([]).datasource_name
    assert default == 'industrial_iot'
    for panel in all_panels(dashboard):
        assert panel['datasource'] == default, panel['title']
