import QtQuick
import Quickshell
import qs.Ui

BarWidget {
  id: root
  moduleName: "osk.toggle"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uF11C"
    tooltipText: "On-screen keyboard (click to toggle)"
    onPressed: function(b) {
      root.bar.run("/home/oz/.local/bin/surface-osk-toggle.sh")
    }
  }
}
