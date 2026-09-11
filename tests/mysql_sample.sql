-- dump estilo mysqldump
CREATE TABLE `tenants` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(150) NOT NULL,
  `key_hash` varchar(64) DEFAULT NULL,
  `checked_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_name` (`name`),
  KEY `idx_checked` (`checked_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `tenant_id` int(11) NOT NULL,
  `email` varchar(320) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_u_t` (`tenant_id`),
  CONSTRAINT `fk_u_t` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE `posts` (
  `id` int(11) NOT NULL,
  `author_id` int(11) DEFAULT NULL,
  `price` decimal(18,2) DEFAULT NULL,
  `flag` tinyint(1) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;

ALTER TABLE `posts` ADD CONSTRAINT `fk_p_u` FOREIGN KEY (`author_id`) REFERENCES `users` (`id`);
