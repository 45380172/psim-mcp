"""bridge_script.py 헬퍼 함수 테스트.

bridge_script.py는 PSIM Python 3.8에서 실행되지만,
순수 함수인 헬퍼들은 테스트 환경에서도 import하여 검증할 수 있다.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import psim_mcp.bridge.bridge_script as bridge_script


def test_get_psim_suppresses_constructor_output(monkeypatch, capsys):
    class FakePsim:
        def __init__(self, psim_path):
            self.psim_path = psim_path
            print("PSIM version 25.0.0.3987")

        def IsValid(self):
            return True

    monkeypatch.setitem(sys.modules, "psimapipy", SimpleNamespace(PSIM=FakePsim))
    monkeypatch.setattr(bridge_script, "_psim_instance", None)
    monkeypatch.setenv("PSIM_PATH", r"C:\Altair\Altair_PSIM_2025")

    instance = bridge_script._get_psim()

    assert instance.psim_path == r"C:\Altair\Altair_PSIM_2025"
    assert capsys.readouterr().out == ""


def test_get_status_accepts_psim_without_version_name(monkeypatch):
    class FakePsim:
        def get_psim_version(self):
            return 25, 0, 0, 3987

    monkeypatch.setattr(bridge_script, "_get_psim", lambda: FakePsim())

    result = bridge_script.handle_get_status({})

    assert result["success"] is True
    assert result["data"]["psim_available"] is True
    assert result["data"]["psim_version"] == "25.0.0.3987"
    assert result["data"]["psim_version_name"] is None


class TestHandleSetParameter:
    def test_maps_alias_parameter_and_persists(self, monkeypatch):
        sch = object()

        class FakePsim:
            def __init__(self):
                self.set_calls = []
                self.save_calls = []

            def PsimSetElmValue2(self, sch_obj, comp_type, comp_name, param_name, value):
                self.set_calls.append((sch_obj, comp_type, comp_name, param_name, value))
                return 1

            def PsimFileSave(self, sch_obj, path):
                self.save_calls.append((sch_obj, path))

        fake_psim = FakePsim()
        monkeypatch.setattr(bridge_script, "_get_psim", lambda: fake_psim)
        monkeypatch.setattr(bridge_script, "_current_sch", sch)
        monkeypatch.setattr(bridge_script, "_current_path", "C:/tmp/forward.psimsch")
        monkeypatch.setattr(bridge_script, "_element_cache", {"G1": "GATING"})

        result = bridge_script.handle_set_parameter(
            {
                "component_id": "G1",
                "parameter_name": "Switching_Points",
                "value": "0,181",
            }
        )

        assert result["success"] is True
        assert result["data"]["psim_parameter_name"] == "Switching_Points"
        assert result["data"]["persisted"] is True
        assert fake_psim.set_calls == [(sch, "GATING", "G1", "Switching_Points", "0,181")]
        assert fake_psim.save_calls == [(sch, "C:/tmp/forward.psimsch")]


def test_element_list_uses_compat_reader_after_vendor_ctypes_failure(monkeypatch):
    class FakePsim:
        def PsimGetElementList(self, sch, flag):
            raise TypeError("unsupported operand type(s) for +: '_ctypes.PyCArrayType' and 'int'")

    expected = [SimpleNamespace(Name="TF_D1", Type="TFCTN_D", Params=[])]
    monkeypatch.setattr(
        bridge_script,
        "_read_element_list_compat",
        lambda psim, sch, flag: expected,
        raising=False,
    )

    assert bridge_script._get_element_list(FakePsim(), object(), 0) == expected


class _FakeConvertFunc:
    def __init__(self, ret, write=True):
        self.ret = ret
        self.write = write

    def __call__(self, src, dst):
        if self.write:
            with open(dst.value, "w", encoding="utf-8") as f:
                f.write("# converted\n")
        return self.ret


def test_convert_via_dll_success(tmp_path):
    out = tmp_path / "out.py"
    fake = SimpleNamespace(psimHandle=SimpleNamespace(ConvertToPythonW=_FakeConvertFunc(1)))
    # ctypes.c_wchar_p arguments expose the original string through .value
    assert bridge_script._convert_via_dll(fake, "a.psimsch", str(out)) is True
    assert out.read_text(encoding="utf-8") == "# converted\n"


def test_convert_via_dll_returns_false_when_dll_reports_error(tmp_path):
    out = tmp_path / "out.py"
    fake = SimpleNamespace(
        psimHandle=SimpleNamespace(ConvertToPythonW=_FakeConvertFunc(0, write=False))
    )
    assert bridge_script._convert_via_dll(fake, "a.psimsch", str(out)) is False


def test_convert_via_dll_returns_false_when_export_missing(tmp_path):
    out = tmp_path / "out.py"
    assert bridge_script._convert_via_dll(SimpleNamespace(psimHandle=object()), "a", str(out)) is False
    assert bridge_script._convert_via_dll(SimpleNamespace(), "a", str(out)) is False
