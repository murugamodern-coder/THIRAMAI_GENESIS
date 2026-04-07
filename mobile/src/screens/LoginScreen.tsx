import React, { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import { useAuth } from "../auth/AuthContext";
import { colors } from "../theme";

export function LoginScreen() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit() {
    if (!email.trim() || !password) {
      Alert.alert("Sign in", "Enter email and password.");
      return;
    }
    setBusy(true);
    try {
      await login(email, password);
    } catch (e) {
      Alert.alert("Sign in failed", e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <StatusBar style="light" />
      <View style={styles.inner}>
        <Text style={styles.title}>THIRAMAI</Text>
        <Text style={styles.sub}>Your day, synced.</Text>

        <TextInput
          style={styles.input}
          placeholder="Email"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          keyboardType="email-address"
          autoCorrect={false}
          value={email}
          onChangeText={setEmail}
        />
        <TextInput
          style={styles.input}
          placeholder="Password"
          placeholderTextColor={colors.muted}
          secureTextEntry
          value={password}
          onChangeText={setPassword}
        />

        <Pressable
          style={[styles.btn, busy && styles.btnDisabled]}
          onPress={() => void onSubmit()}
          disabled={busy}
        >
          {busy ? (
            <ActivityIndicator color="#022c22" />
          ) : (
            <Text style={styles.btnText}>Sign in</Text>
          )}
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  inner: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 24,
    paddingBottom: 48,
  },
  title: {
    fontSize: 28,
    fontWeight: "700",
    color: colors.text,
    letterSpacing: 2,
  },
  sub: { marginTop: 8, marginBottom: 32, color: colors.muted, fontSize: 15 },
  input: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 14,
    fontSize: 16,
    color: colors.text,
    marginBottom: 12,
  },
  btn: {
    marginTop: 8,
    backgroundColor: colors.accent,
    paddingVertical: 16,
    borderRadius: 10,
    alignItems: "center",
  },
  btnDisabled: { opacity: 0.7 },
  btnText: { fontSize: 16, fontWeight: "600", color: "#022c22" },
});
