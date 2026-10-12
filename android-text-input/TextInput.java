package local.bkkactive.textinput;

import android.app.Instrumentation;
import android.os.Bundle;
import android.util.Base64;
import android.view.accessibility.AccessibilityNodeInfo;
import java.nio.charset.StandardCharsets;

/** Sets the focused app's EditText through accessibility, including Thai text. */
public class TextInput extends Instrumentation {
    private String text;

    @Override public void onCreate(Bundle arguments) {
        text = new String(Base64.decode(arguments.getString("text64"), Base64.DEFAULT),
                          StandardCharsets.UTF_8);
        start();
    }

    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
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
