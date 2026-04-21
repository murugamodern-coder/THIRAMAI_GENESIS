CREATE TABLE IF NOT EXISTS os_settings (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  org_id      INT NOT NULL DEFAULT 1,
  os_key      VARCHAR(50) NOT NULL,
  field       VARCHAR(100) NOT NULL,
  value       TEXT,
  updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY unique_setting (org_id, os_key, field)
);

-- Insert default empty settings for all 5 OS
INSERT IGNORE INTO os_settings (org_id, os_key, field, value) VALUES
  (1, 'personal', 'lindy_api_key',    ''),
  (1, 'personal', 'motion_api_key',   ''),
  (1, 'personal', 'reclaim_oauth',    ''),
  (1, 'stock',    'quiver_api_key',   ''),
  (1, 'stock',    'bloomberg_key',    ''),
  (1, 'stock',    'risk_alert_score', '70'),
  (1, 'research', 'perplexity_key',   ''),
  (1, 'research', 'openai_key',       ''),
  (1, 'agentic',  'github_token',     ''),
  (1, 'agentic',  'replit_token',     '');
