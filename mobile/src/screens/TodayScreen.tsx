import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { useAuth } from "../auth/AuthContext";
import { useToday } from "../context/TodayContext";
import { presentFirstAlertLine, requestAlertPermission } from "../lib/localAlert";
import { getNotifyAlertsEnabled, setNotifyAlertsEnabled } from "../lib/notifyPrefs";
import { colors } from "../theme";

export function TodayScreen() {
  const { logout } = useAuth();
  const { today, loading, error, refresh } = useToday();
  const g = today?.guidance;
  const [notifyAlerts, setNotifyAlerts] = useState(false);
  const alertsSeededRef = useRef(false);
  const prevAlertCountRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const on = await getNotifyAlertsEnabled();
      if (!cancelled) setNotifyAlerts(on);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const n = g?.alerts?.length ?? 0;
    if (!alertsSeededRef.current) {
      alertsSeededRef.current = true;
      prevAlertCountRef.current = n;
      return;
    }
    if (notifyAlerts && n > prevAlertCountRef.current && n > 0) {
      const first = g?.alerts?.[0];
      if (first) void presentFirstAlertLine(first);
    }
    prevAlertCountRef.current = n;
  }, [g?.alerts, notifyAlerts]);

  const onToggleNotify = async (on: boolean) => {
    if (on) {
      const ok = await requestAlertPermission();
      if (!ok) return;
    }
    await setNotifyAlertsEnabled(on);
    setNotifyAlerts(on);
  };

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Today</Text>
        <Pressable onPress={() => void logout()} hitSlop={8}>
          <Text style={styles.logout}>Log out</Text>
        </Pressable>
      </View>

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
        {error ? (
          <Text style={styles.error}>{error}</Text>
        ) : loading && !today ? (
          <ActivityIndicator size="large" color={colors.accent} style={{ marginTop: 24 }} />
        ) : (
          <>
            <View style={styles.row}>
              <Text style={styles.statLabel}>Streak</Text>
              <Text style={styles.statVal}>{today?.streak_days ?? "—"} days</Text>
            </View>
            <View style={styles.row}>
              <Text style={styles.statLabel}>Score</Text>
              <Text style={styles.statVal}>{today?.daily_score ?? "—"} / 100</Text>
            </View>

            <View style={styles.notifyRow}>
              <View style={{ flex: 1, paddingRight: 12 }}>
                <Text style={styles.notifyLabel}>Notify on new alerts</Text>
                <Text style={styles.notifyHint}>
                  Local notification when a new alert appears (foreground refresh).
                </Text>
              </View>
              <Switch
                value={notifyAlerts}
                onValueChange={(v) => void onToggleNotify(v)}
                trackColor={{ false: colors.border, true: "#14532d" }}
                thumbColor={notifyAlerts ? colors.accent : "#888"}
              />
            </View>

            <Text style={styles.section}>Focus</Text>
            <Text style={styles.focus}>{g?.top_focus || g?.focus || "—"}</Text>

            <Text style={styles.section}>Alerts</Text>
            {g?.alerts?.length ? (
              g.alerts.map((a, i) => (
                <Text key={i} style={styles.alertLine}>
                  • {a}
                </Text>
              ))
            ) : (
              <Text style={styles.muted}>No alerts.</Text>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: { fontSize: 20, fontWeight: "700", color: colors.text },
  logout: { color: colors.muted, fontSize: 14 },
  scroll: { padding: 16, paddingBottom: 32 },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  statLabel: { color: colors.muted, fontSize: 14 },
  statVal: { color: colors.accent, fontSize: 14, fontWeight: "600" },
  notifyRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 16,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  notifyLabel: { color: colors.text, fontSize: 14, fontWeight: "600" },
  notifyHint: { color: colors.muted, fontSize: 12, marginTop: 4, lineHeight: 16 },
  section: {
    marginTop: 20,
    marginBottom: 8,
    fontSize: 12,
    fontWeight: "600",
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  focus: { fontSize: 17, lineHeight: 24, color: colors.text, fontWeight: "500" },
  alertLine: { fontSize: 14, color: colors.warn, marginBottom: 6, lineHeight: 20 },
  muted: { color: colors.muted, fontSize: 14 },
  error: { color: colors.err, fontSize: 14, marginTop: 8 },
});
