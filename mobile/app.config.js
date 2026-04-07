/**
 * Override API base without editing app.json:
 *   EXPO_PUBLIC_API_URL=http://192.168.1.10:8000 npx expo start
 */
module.exports = ({ config }) => ({
  ...config,
  extra: {
    ...config.extra,
    apiUrl: process.env.EXPO_PUBLIC_API_URL || config.extra?.apiUrl || "http://127.0.0.1:8000",
  },
});
