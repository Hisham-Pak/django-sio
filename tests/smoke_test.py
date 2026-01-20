# tests/smoke_test.py


def test_import():
    # Try importing the package you just built
    import sio

    # Optionally check a simple attribute or function exists
    assert hasattr(sio, "__version__")


if __name__ == "__main__":
    # Run the test manually if not using pytest
    test_import()
    print("Smoke test passed ✅")
