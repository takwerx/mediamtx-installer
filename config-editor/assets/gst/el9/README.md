# Prebuilt GStreamer `rtspclientsink` plugin for RHEL/Rocky 9

`libgstrtspclientsink.so` — the `rtspclientsink` element, **not packaged** for EL9
(EPEL/CRB/RPM Fusion ship only `libgstrtspserver`, not this plugin). Required for
the console's RTSP "Send to Remote" KLV push on Rocky. The console's Versions tab
("Update GStreamer") fetches this file and drops it into `/usr/lib64/gstreamer-1.0/`.

**ABI-coupled to the runtime GStreamer version** (built against 1.22.12, el9, x86-64).
If the box's GStreamer differs, rebuild:

```
dnf install -y gcc meson ninja-build gstreamer1-devel \
  gstreamer1-plugins-base-devel glib2-devel pkgconf-pkg-config
curl -LO https://gstreamer.freedesktop.org/src/gst-rtsp-server/gst-rtsp-server-<VER>.tar.xz
tar xf gst-rtsp-server-<VER>.tar.xz && cd gst-rtsp-server-<VER>
meson setup builddir -Dtests=disabled -Dexamples=disabled -Dintrospection=disabled
ninja -C builddir
cp builddir/gst/rtsp-sink/libgstrtspclientsink.so /usr/lib64/gstreamer-1.0/
```
