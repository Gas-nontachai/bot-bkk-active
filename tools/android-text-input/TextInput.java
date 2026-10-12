package local.bkkactive.textinput;

import android.app.Instrumentation;
import android.os.Bundle;
import android.graphics.Rect;
import android.util.Base64;
import android.util.Xml;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import org.xmlpull.v1.XmlSerializer;

/** Sets the focused app's EditText through accessibility, including Thai text. */
public class TextInput extends Instrumentation {
    private String text;
    private String action;

    @Override public void onCreate(Bundle arguments) {
        action = arguments.getString("action", "text");
        if ("text".equals(action)) {
            text = new String(Base64.decode(arguments.getString("text64"), Base64.DEFAULT),
                              StandardCharsets.UTF_8);
        }
        start();
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            if ("version".equals(action)) {
                result.putString("result", "BRIDGE_VERSION_3");
                finish(-1, result);
                return;
            }
            if ("dump".equals(action)) {
                AccessibilityNodeInfo root = null;
                for (int attempt = 0; attempt < 20 && root == null; attempt++) {
                    root = getUiAutomation().getRootInActiveWindow();
                    if (root == null) android.os.SystemClock.sleep(50);
                }
                if (root == null) throw new IllegalStateException("Active window not found");
                StringWriter writer = new StringWriter();
                XmlSerializer xml = Xml.newSerializer();
                xml.setOutput(writer);
                xml.startDocument("UTF-8", true);
                xml.startTag(null, "hierarchy");
                Rect bounds = new Rect();
                root.getBoundsInScreen(bounds);
                dumpNode(xml, root, bounds, 0);
                xml.endTag(null, "hierarchy");
                xml.endDocument();
                result.putString("xml64", Base64.encodeToString(
                    writer.toString().getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP));
                finish(-1, result);
                return;
            }
            if (!"text".equals(action)) throw new IllegalArgumentException("Unknown action");
            AccessibilityNodeInfo field = null;
            for (int attempt = 0; attempt < 10 && field == null; attempt++) {
                field = findField(getUiAutomation().getRootInActiveWindow());
                if (field == null) android.os.SystemClock.sleep(500);
            }
            if (field == null) throw new IllegalStateException("Search EditText not found");
            Bundle arguments = new Bundle();
            arguments.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            if (!field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments))
                throw new IllegalStateException("ACTION_SET_TEXT failed");
            result.putString("result", "TEXT_SET_OK");
            finish(-1, result);
        } catch (Exception error) {
            result.putString("error", error.toString());
            finish(0, result);
        }
    }

    private void dumpNode(XmlSerializer xml, AccessibilityNodeInfo node, Rect clip, int index)
            throws Exception {
        if (node == null || !node.isVisibleToUser()) return;
        Rect rect = new Rect();
        node.getBoundsInScreen(rect);
        if (!rect.intersect(clip)) return;
        xml.startTag(null, "node");
        xml.attribute(null, "index", Integer.toString(index));
        xml.attribute(null, "text", clean(node.getText()));
        xml.attribute(null, "content-desc", clean(node.getContentDescription()));
        xml.attribute(null, "package", clean(node.getPackageName()));
        xml.attribute(null, "class", clean(node.getClassName()));
        xml.attribute(null, "resource-id", clean(node.getViewIdResourceName()));
        xml.attribute(null, "clickable", Boolean.toString(node.isClickable()));
        xml.attribute(null, "enabled", Boolean.toString(node.isEnabled()));
        xml.attribute(null, "selected", Boolean.toString(node.isSelected()));
        xml.attribute(null, "scrollable", Boolean.toString(node.isScrollable()));
        xml.attribute(null, "focused", Boolean.toString(node.isFocused()));
        xml.attribute(null, "bounds", "[" + rect.left + "," + rect.top + "]["
                      + rect.right + "," + rect.bottom + "]");
        for (int i = 0; i < node.getChildCount(); i++) {
            dumpNode(xml, node.getChild(i), rect, i);
        }
        xml.endTag(null, "node");
    }

    private String clean(CharSequence value) {
        if (value == null) return "";
        // Drop control characters forbidden by XML 1.0.
        return value.toString().replaceAll("[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F]", "");
    }

    private AccessibilityNodeInfo findField(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if ("go.th.bangkok.cstd".contentEquals(node.getPackageName())
                && "android.widget.EditText".contentEquals(node.getClassName())
                && node.isVisibleToUser()) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo found = findField(node.getChild(i));
            if (found != null) return found;
        }
        return null;
    }
}
