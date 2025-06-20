import io
import json
import shutil
import subprocess
import zipfile
from http.client import HTTPMessage
from unittest.mock import MagicMock, Mock, mock_open, patch
from urllib.error import HTTPError

import pytest

from nixpkgs_review.cli import main
from nixpkgs_review.utils import nix_nom_tool

from .conftest import Helpers


def create_mock_pr_response(
    pr_number: int = 1,
    title: str = "Example PR",
    body: str = "This is a test PR",
) -> dict:
    """Create a mock GitHub PR response."""
    return {
        "number": pr_number,
        "head": {
            "ref": "example-branch",
            "sha": "abc123",
            "label": "user:example-branch",
        },
        "base": {"ref": "master", "label": "NixOS:master"},
        "title": title,
        "html_url": f"https://github.com/NixOS/nixpkgs/pull/{pr_number}",
        "user": {"login": "test-user"},
        "state": "open",
        "body": body,
        "diff_url": f"https://github.com/NixOS/nixpkgs/pull/{pr_number}.diff",
        "draft": False,
    }


def create_mock_diff_content() -> str:
    """Create a mock diff content."""
    return """diff --git a/pkg1.txt b/pkg1.txt
new file mode 100644
index 0000000..1910281
--- /dev/null
+++ b/pkg1.txt
@@ -0,0 +1 @@
+foo"""


def setup_pr_mocks(
    mock_urlopen: MagicMock, pr_number: int = 1, additional_mocks: list | None = None
) -> None:
    """Set up standard mock responses for PR tests."""
    pr_response = create_mock_pr_response(pr_number)
    diff_content = create_mock_diff_content()

    mocks = [
        mock_open(read_data=json.dumps(pr_response).encode())(),
        mock_open(read_data=diff_content.encode())(),
    ]

    if additional_mocks:
        mocks.extend(additional_mocks)

    mock_urlopen.side_effect = mocks


@patch("nixpkgs_review.utils.shutil.which", return_value=None)
def test_default_to_nix_if_nom_not_found(mock_shutil: Mock) -> None:
    return_value = nix_nom_tool()
    assert return_value == "nix"
    mock_shutil.assert_called_once()


@pytest.mark.skipif(not shutil.which("nom"), reason="`nom` not found in PATH")
def test_pr_local_eval(helpers: Helpers, capfd: pytest.CaptureFixture) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/1/merge"], check=True)
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/merge"], check=True)

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "1",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        captured = capfd.readouterr()
        assert "$ nom build" in captured.out


@patch("urllib.request.urlopen")
@patch("nixpkgs_review.cli.nix_nom_tool", return_value="nix")
def test_pr_local_eval_missing_nom(
    mock_tool: Mock,
    mock_urlopen: MagicMock,
    helpers: Helpers,
    capfd: pytest.CaptureFixture,
) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/1/merge"], check=True)
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/merge"], check=True)

        setup_pr_mocks(mock_urlopen, pr_number=1)

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "1",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        mock_tool.assert_called_once()
        captured = capfd.readouterr()
        assert "$ nix build" in captured.out


@patch("urllib.request.urlopen")
def test_pr_local_eval_without_nom(
    mock_urlopen: MagicMock, helpers: Helpers, capfd: pytest.CaptureFixture
) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/1/merge"], check=True)
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/merge"], check=True)

        setup_pr_mocks(mock_urlopen, pr_number=1)

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "1",
                "--build-graph",
                "nix",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
        captured = capfd.readouterr()
        assert "$ nix build" in captured.out


@pytest.mark.skipif(not shutil.which("bwrap"), reason="`bwrap` not found in PATH")
def test_pr_local_eval_with_sandbox(helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/1/merge"], check=True)
        subprocess.run(["git", "push", str(nixpkgs.remote), "pull/1/merge"], check=True)

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--sandbox",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "1",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)


@patch("urllib.request.urlopen")
def test_pr_ofborg_eval(mock_urlopen: MagicMock, helpers: Helpers) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/37200/merge"], check=True)
        subprocess.run(
            ["git", "push", str(nixpkgs.remote), "pull/37200/merge"], check=True
        )

        # Set up mocks for ofborg eval
        additional_mocks = [
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_ofborg_eval/github-workflows-37200.json"
                ).encode()
            )(),
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_ofborg_eval/github-pull-37200-statuses.json"
                ).encode()
            )(),
            helpers.read_asset("test_pr_ofborg_eval/gist-37200.txt")
            .encode("utf-8")
            .split(b"\n"),
        ]

        # Use custom PR response from asset file
        mock_urlopen.side_effect = [
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_ofborg_eval/github-pull-37200.json"
                ).encode()
            )(),
            mock_open(read_data=create_mock_diff_content().encode())(),
            *additional_mocks,
        ]

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--eval",
                "local",
                "--run",
                "exit 0",
                "37200",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)


@patch("urllib.request.urlopen")
def test_pr_github_action_eval(
    mock_urlopen: MagicMock,
    helpers: Helpers,
) -> None:
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/363128/merge"], check=True)
        subprocess.run(
            ["git", "push", str(nixpkgs.remote), "pull/363128/merge"], check=True
        )

        # Create minimal fake zip archive that could have been generated by the `comparison` GH action.
        mock_zip = io.BytesIO()
        with zipfile.ZipFile(mock_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "changed-paths.json",
                helpers.read_asset(
                    "test_pr_github_action_eval/comparison-changed-paths.json"
                ),
            )
        mock_zip.seek(0)

        # Set up mocks for github action eval
        additional_mocks = [
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_github_action_eval/github-workflows-363128.json"
                ).encode()
            )(),
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_github_action_eval/github-artifacts-363128.json"
                ).encode()
            )(),
            mock_open(read_data=mock_zip.getvalue())(),
        ]

        # Use custom PR response from asset file
        mock_urlopen.side_effect = [
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_github_action_eval/github-pull-363128.json"
                ).encode()
            )(),
            mock_open(read_data=create_mock_diff_content().encode())(),
            *additional_mocks,
        ]

        hdrs = HTTPMessage()
        hdrs.add_header("Location", "http://example.com")
        http_error = HTTPError(
            url="http://example.com",
            code=302,
            msg="Found",
            hdrs=hdrs,
            fp=None,
        )

        with patch(
            "nixpkgs_review.github.no_redirect_opener.open", side_effect=http_error
        ):
            path = main(
                "nixpkgs-review",
                [
                    "pr",
                    "--remote",
                    str(nixpkgs.remote),
                    "--run",
                    "exit 0",
                    "363128",
                ],
            )
            helpers.assert_built(pkg_name="pkg1", path=path)


@patch("urllib.request.urlopen")
@patch("nixpkgs_review.review._list_packages_system")
def test_pr_only_packages_does_not_trigger_an_eval(
    mock_eval: MagicMock,
    mock_urlopen: MagicMock,
    helpers: Helpers,
) -> None:
    mock_eval.side_effect = RuntimeError
    with helpers.nixpkgs() as nixpkgs:
        nixpkgs.path.joinpath("pkg1.txt").write_text("foo")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", "example-change"], check=True)
        subprocess.run(["git", "checkout", "-b", "pull/363128/merge"], check=True)
        subprocess.run(
            ["git", "push", str(nixpkgs.remote), "pull/363128/merge"], check=True
        )

        # Use custom PR response from asset file
        mock_urlopen.side_effect = [
            mock_open(
                read_data=helpers.read_asset(
                    "test_pr_github_action_eval/github-pull-363128.json"
                ).encode()
            )(),
            mock_open(read_data=create_mock_diff_content().encode())(),
        ]

        path = main(
            "nixpkgs-review",
            [
                "pr",
                "--remote",
                str(nixpkgs.remote),
                "--run",
                "exit 0",
                "--package",
                "pkg1",
                "363128",
            ],
        )
        helpers.assert_built(pkg_name="pkg1", path=path)
