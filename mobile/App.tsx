import React from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { NavigationContainer, DarkTheme } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { AuthProvider, useAuth } from "./src/auth/AuthContext";
import { TodayProvider } from "./src/context/TodayContext";
import { LoginScreen } from "./src/screens/LoginScreen";
import { TodayScreen } from "./src/screens/TodayScreen";
import { ActionScreen } from "./src/screens/ActionScreen";
import { SummaryScreen } from "./src/screens/SummaryScreen";
import { colors } from "./src/theme";

const Tab = createBottomTabNavigator();

const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.bg,
    card: colors.bg,
    border: colors.border,
    primary: colors.accent,
    text: colors.text,
  },
};

function MainTabs({ token }: { token: string }) {
  return (
    <TodayProvider token={token}>
      <Tab.Navigator
        screenOptions={{
          headerShown: false,
          tabBarStyle: {
            backgroundColor: colors.card,
            borderTopColor: colors.border,
          },
          tabBarActiveTintColor: colors.accent,
          tabBarInactiveTintColor: colors.muted,
          tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
        }}
      >
        <Tab.Screen name="Today" component={TodayScreen} />
        <Tab.Screen name="Actions" component={ActionScreen} />
        <Tab.Screen name="Summary" component={SummaryScreen} />
      </Tab.Navigator>
    </TodayProvider>
  );
}

function Gate() {
  const { token, ready } = useAuth();
  if (!ready) {
    return (
      <View style={styles.boot}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }
  if (!token) {
    return <LoginScreen />;
  }
  return (
    <NavigationContainer theme={navTheme}>
      <MainTabs token={token} />
    </NavigationContainer>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <AuthProvider>
          <Gate />
        </AuthProvider>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  boot: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
  },
});
