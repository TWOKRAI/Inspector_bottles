use std::collections::HashMap;

/// Configuration for the application
pub struct Config {
    pub name: String,
    pub settings: HashMap<String, String>,
}

impl Config {
    /// Create a new configuration with defaults
    pub fn new(name: &str) -> Self {
        Self {
            name: name.to_string(),
            settings: HashMap::new(),
        }
    }

    /// Get a setting value
    pub fn get(&self, key: &str) -> Option<&String> {
        self.settings.get(key)
    }

    /// Set a configuration value
    pub fn set(&mut self, key: String, value: String) {
        self.settings.insert(key, value);
    }
}

/// Process the configuration and return a summary
pub fn process_config(config: &Config) -> String {
    format!(
        "Config '{}' has {} settings",
        config.name,
        config.settings.len()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_new() {
        let config = Config::new("test");
        assert_eq!(config.name, "test");
        assert!(config.settings.is_empty());
    }
}
