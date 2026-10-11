import json

from pet.config import APP_DIR_NAME, Config
from pet import pet_profiles as profiles
from pet.settings_slot_config import route_settings_config


def test_migration_cleans_source_and_normalizes(tmp_path):
    directory = tmp_path / APP_DIR_NAME
    directory.mkdir()
    source = directory / 'config.json'
    source.write_text(json.dumps({'version': 1, 'scale': 2, 'character': 'cat',
                                  'voice_chime_enabled': True}), encoding='utf8')
    result = profiles.migrate_slot0_profile(directory)
    assert result.ok
    original = source.with_name(source.name + profiles.PROFILE_MIGRATION_BACKUP_SUFFIX).read_bytes()
    assert 'character' not in json.loads(source.read_text(encoding='utf8'))
    assert profiles.migrate_slot0_profile(directory).ok
    assert source.with_name(source.name + profiles.PROFILE_MIGRATION_BACKUP_SUFFIX).read_bytes() == original


def test_explicit_global_ignores_instance_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_PET_INSTANCE', 'slot-128')
    assert Config(base=tmp_path, instance_id='').path.name == 'config.json'


def test_profile_draft_cannot_cross_reset(tmp_path):
    directory = tmp_path / APP_DIR_NAME
    profiles.write_profile_settings(directory, 0, {'scale': 0.8, 'rx': 0.2, 'ry': 0.3})
    cfg = route_settings_config(Config(base=tmp_path, instance_id='slot-0'))
    cfg.set('scale', 1.4)
    assert profiles.reset_slot_profile(directory, 0).ok
    cfg.reload()
    assert not cfg.save()
    assert profiles.read_slot_profile(directory, 0).value('rx') == 0.2


def test_global_save_never_resurrects_migrated_pet_keys(tmp_path):
    cfg = Config(base=tmp_path, instance_id='')
    cfg.set('character', 'cat')
    cfg.save()
    assert profiles.migrate_slot0_profile(cfg.dir).ok
    cfg.set('voice_chime_enabled', True)
    assert cfg.save()
    assert not (profiles.PER_PET_KEYS & json.loads(cfg.path.read_text(encoding='utf8')).keys())


def test_global_reset_preserves_all_profiles_and_active(tmp_path):
    cfg = Config(base=tmp_path, instance_id='')
    for n in (0, 1, 128):
        profiles.write_profile_settings(cfg.dir, n, {'rx': n / 128, 'scale': 0.9})
    profiles.save_active_set(cfg.dir, [1, 128])
    paths = [profiles.slot_profile_path(cfg.dir, n) for n in (0, 1, 128)]
    paths.append(profiles.active_set_path(cfg.dir))
    before = {path: path.read_bytes() for path in paths}
    assert cfg.reset_to_defaults()
    assert all(path.read_bytes() == before[path] for path in paths)


def test_raw_slot_config_cannot_write(tmp_path):
    cfg = Config(base=tmp_path, instance_id='slot-128')
    cfg.set('scale', 1.2)
    assert not cfg.save()
    assert not cfg.path.exists()


def test_partial_reset_blocks_new_reader_save(tmp_path, monkeypatch):
    from pet import config_write_lock as cwl
    directory = tmp_path / APP_DIR_NAME
    profiles.write_profile_settings(directory, 0, {'scale': 1.2})
    real = cwl.atomic_write_json
    def fail(path, data):
        if path == profiles.slot_profile_path(directory, 0):
            raise cwl.AtomicWriteFailed('injected')
        real(path, data)
    with monkeypatch.context() as patch:
        patch.setattr(cwl, 'atomic_write_json', fail)
        assert profiles.reset_slot_profile(directory, 0).status == 'partial'
    snapshot = profiles.read_slot_snapshot(directory, 0)
    result = profiles.write_profile_settings(directory, 0, {'scale': 1.4},
                                             generation=snapshot.generation)
    assert not result.ok
    assert profiles.reset_slot_profile(directory, 0).ok

