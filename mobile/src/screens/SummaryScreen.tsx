import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { fetchPersonalSummary } from "../api/client";
import type { PersonalSummaryResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { colors } from "../theme";

export function SummaryScreen() {
  const { token } = useAuth();
  const [data, setData] = useState<PersonalSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const j = await fetchPersonalSummary(token);
      setData(j);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const ev = data?.evening;

  return (
    <View style={styles.root}>
      <Text style={styles.title}>Summary</Text>
      <Text style={styles.sub}>Evening wrap · pull to refresh</Text>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={() => void load()}
            tintColor={colors.accent}
          />
        }
      >
        {data ? (
          <View style={styles.meta}>
            <Text style={styles.metaText}>
              Streak {data.streak_days ?? "—"} · Score {data.daily_score ?? "—"}/100
            </Text>
          </View>
        ) : null}

        {error ? <Text style={styles.error}>{error}</Text> : null}
        {loading && !data ? (
          <ActivityIndicator size="large" color={colors.accent} style={{ marginTop: 24 }} />
        ) : null}

        {ev ? (
          <>
            <Text style={styles.section}>Overview</Text>
            <Text style={styles.body}>{ev.summary || "—"}</Text>

            <Text style={styles.section}>Wins</Text>
            {ev.wins?.length ? (
              ev.wins.map((w, i) => (
                <Text key={i} style={styles.bullet}>
                  • {w}
                </Text>
              ))
            ) : (
              <Text style={styles.muted}>—</Text>
            )}

            <Text style={styles.section}>Carry forward</Text>
            {ev.carry_over?.length ? (
              ev.carry_over.map((w, i) => (
                <Text key={i} style={styles.bulletMuted}>
                  • {w}
                </Text>
              ))
            ) : (
              <Text style={styles.muted}>—</Text>
            )}

            {ev.tomorrow_hint ? (
              <>
                <Text style={styles.section}>Tomorrow</Text>
                <Text style={styles.tomorrow}>{ev.tomorrow_hint}</Text>
              </>
            ) : null}
          </>
        ) : !loading && !error ? (
          <Text style={styles.muted}>No summary yet.</Text>
        ) : null}
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
  meta: { marginBottom: 16 },
  metaText: { color: colors.accent, fontSize: 13, fontWeight: "500" },
  section: {
    marginTop: 16,
    marginBottom: 8,
    fontSize: 12,
    fontWeight: "600",
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  body: { fontSize: 15, lineHeight: 22, color: colors.text },
  bullet: { fontSize: 14, color: "#a7f3d0", marginBottom: 6, lineHeight: 20 },
  bulletMuted: { fontSize: 14, color: colors.muted, marginBottom: 6, lineHeight: 20 },
  tomorrow: { fontSize: 14, lineHeight: 20, color: colors.text, fontStyle: "italic" },
  muted: { color: colors.muted, fontSize: 14 },
  error: { color: colors.err, fontSize: 14, marginBottom: 8 },
});
