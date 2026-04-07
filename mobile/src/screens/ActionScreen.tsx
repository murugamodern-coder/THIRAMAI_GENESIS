import React, { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { postPersonalAction } from "../api/client";
import type { ActionableSuggestion } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToday } from "../context/TodayContext";
import { colors } from "../theme";

export function ActionScreen() {
  const { token } = useAuth();
  const { today, loading, error, refresh } = useToday();
  const [runningIdx, setRunningIdx] = useState<number | null>(null);

  const items = today?.guidance?.actionable_suggestions ?? [];

  async function runAction(sug: ActionableSuggestion, index: number) {
    if (!token || !sug.body || typeof sug.body !== "object") {
      Alert.alert("Action", "Nothing to run for this item.");
      return;
    }
    setRunningIdx(index);
    try {
      const out = await postPersonalAction(token, sug.body as Record<string, unknown>);
      Alert.alert(
        "Done",
        out.message || (out.executed ? "Executed." : "OK — check app for next steps.")
      );
      await refresh();
    } catch (e) {
      Alert.alert("Action failed", e instanceof Error ? e.message : String(e));
    } finally {
      setRunningIdx(null);
    }
  }

  return (
    <View style={styles.root}>
      <Text style={styles.title}>Actions</Text>
      <Text style={styles.sub}>One tap — uses your signed-in org.</Text>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={() => void refresh()}
            tintColor={colors.accent}
          />
        }
      >
        {error ? <Text style={styles.error}>{error}</Text> : null}
        {!items.length && !loading ? (
          <Text style={styles.muted}>No suggested actions right now.</Text>
        ) : null}
        {items.map((sug, i) => {
          const key = `${sug.action}-${i}`;
          const busy = runningIdx === i;
          const canRun =
            sug.action_type === "api_call" &&
            sug.body &&
            typeof sug.body === "object";
          return (
            <View key={key} style={styles.card}>
              <Text style={styles.cardText}>{sug.text || sug.action || "Action"}</Text>
              {canRun ? (
                <Pressable
                  style={[styles.runBtn, busy && styles.runBtnDisabled]}
                  onPress={() => void runAction(sug, i)}
                  disabled={runningIdx !== null}
                >
                  {busy ? (
                    <ActivityIndicator color="#022c22" size="small" />
                  ) : (
                    <Text style={styles.runBtnText}>Run</Text>
                  )}
                </Pressable>
              ) : (
                <Text style={styles.hint}>Open from Today / web for this step.</Text>
              )}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg, paddingTop: 8 },
  title: {
    fontSize: 20,
    fontWeight: "700",
    color: colors.text,
    paddingHorizontal: 16,
  },
  sub: {
    fontSize: 13,
    color: colors.muted,
    paddingHorizontal: 16,
    marginTop: 4,
    marginBottom: 12,
  },
  scroll: { paddingHorizontal: 16, paddingBottom: 32 },
  card: {
    backgroundColor: colors.card,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 14,
    marginBottom: 12,
  },
  cardText: { color: colors.text, fontSize: 15, lineHeight: 22 },
  runBtn: {
    marginTop: 12,
    alignSelf: "flex-start",
    backgroundColor: colors.accent,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 8,
  },
  runBtnDisabled: { opacity: 0.6 },
  runBtnText: { color: "#022c22", fontWeight: "600", fontSize: 14 },
  hint: { marginTop: 8, fontSize: 12, color: colors.muted },
  muted: { color: colors.muted, fontSize: 14 },
  error: { color: colors.err, marginBottom: 12, fontSize: 14 },
});
