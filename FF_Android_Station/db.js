// Database management with Dexie.js for Tablet Offline Storage
const db = new Dexie("FF_Offline_DB");

// Define schema
db.version(1).stores({
    timings: "++id, race_id, ss, line, timestamp, ns, penalty, status, is_synced", // status: 'local', 'pending', 'synced'
    settings: "key, value"
});

// Helper functions for Offline/Online logic
const FF_DB = {
    async addLocalTiming(race_id, ss, line, timestamp) {
        return await db.timings.add({
            race_id: race_id,
            ss: ss,
            line: line,
            timestamp: timestamp,
            ns: "-",
            penalty: 0,
            status: "local",
            is_synced: false,
            created_at: new Date().getTime()
        });
    },

    async getUnsynced() {
        return await db.timings.where("is_synced").equals(0).toArray();
    },

    async markSynced(id) {
        return await db.timings.update(id, { is_synced: true, status: "synced" });
    },

    async saveSetting(key, value) {
        return await db.settings.put({ key, value });
    },

    async getSetting(key) {
        const item = await db.settings.get(key);
        return item ? item.value : null;
    }
};
