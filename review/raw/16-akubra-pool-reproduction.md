# B17 validation handoff

B17 is a source-level finding: both FOXML unmarshal paths borrow an object from a pool of 50 and return it only after successful parsing. Repeated failures can therefore deplete the pool. Its production incidence is unknown.

A local JUnit fixture was briefly attempted, but Akubra compilation stopped before the test could run because `org.ceskaexpedice:hazelcast-locks-server:2.0` was unavailable from the configured repositories. The attempted fixture was removed after the operator clarified that tests belong in the Kramerius benchmarking environment being developed in another session. **No B17 test has run and no application code has changed.**

When that environment is ready, validate a malformed FOXML read by checking that the unmarshaller pool retains its size and later valid reads complete; cover both `unmarshallObject` and `readObjectFromStorage`. Keep the validation isolated from production data and worker availability. B15 should be checked in the same environment with one injected document-indexing failure, verifying job status, counters, and retry marker. These are handoff criteria, not current test work.
