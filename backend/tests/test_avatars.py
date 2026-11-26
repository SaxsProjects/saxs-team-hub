"""Profile pictures: cleaned on upload, private to signed-in users."""

import io

from PIL import Image

from app import avatars


def jpeg_with_gps(size=(1200, 800)) -> bytes:
    img = Image.new("RGB", size, (0, 102, 255))
    exif = Image.Exif()
    exif[0x8825] = {1: "S", 2: (22.0, 58.0, 0.0), 3: "E", 4: (30.0, 29.0, 0.0)}  # GPS near Thohoyandou
    exif[0x010F] = "PhoneMaker"
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def upload(client, headers, data, name="me.jpg", ctype="image/jpeg"):
    return client.put("/api/me/avatar", headers=headers, files={"file": (name, data, ctype)})


def test_upload_strips_metadata_and_resizes(client, admin):
    original = jpeg_with_gps()
    assert b"PhoneMaker" in original
    r = upload(client, admin, original)
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert url.startswith("/api/avatars/") and "?v=" in url
    assert client.get("/api/auth/me", headers=admin).json()["avatar_url"] == url

    pic = client.get(url, headers=admin)
    assert pic.status_code == 200 and pic.headers["content-type"] == "image/webp"
    assert "private" in pic.headers["cache-control"]
    with Image.open(io.BytesIO(pic.content)) as img:
        assert img.format == "WEBP" and img.size == (512, 512)
        assert not img.getexif()
    assert b"PhoneMaker" not in pic.content


def test_rejects_non_images_and_bombs(client, admin, monkeypatch):
    assert upload(client, admin, b"<script>alert(1)</script>", "x.jpg").status_code == 400
    assert upload(client, admin, b"%PDF-1.4 not an image", "x.png", "image/png").status_code == 400
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, format="GIF")
    assert upload(client, admin, gif.getvalue(), "x.gif", "image/gif").status_code == 400
    monkeypatch.setattr(avatars, "MAX_SOURCE_PIXELS", 100)
    assert upload(client, admin, jpeg_with_gps((20, 20))).status_code == 400
    monkeypatch.setattr(avatars, "MAX_UPLOAD_BYTES", 10)
    assert upload(client, admin, jpeg_with_gps((20, 20))).status_code == 413


def test_pictures_are_private_and_visible_to_the_team(client, admin, team):
    person, member = team
    url = upload(client, member, jpeg_with_gps((300, 300))).json()["avatar_url"]
    assert client.get(url).status_code == 401  # never public
    assert client.get(url, headers=admin).status_code == 200
    [listed] = [p for p in client.get("/api/people", headers=admin).json() if p["id"] == person["id"]]
    assert listed["avatar_url"] == url

    assert client.delete("/api/me/avatar", headers=member).status_code == 204
    assert client.get(url, headers=admin).status_code == 404
    assert client.get("/api/auth/me", headers=member).json()["avatar_url"] is None
