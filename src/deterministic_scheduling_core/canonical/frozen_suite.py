from __future__ import annotations


EXPECTED_CASE_IDS = (
    *(f"SEM-REL-{number:03d}" for number in range(1, 13)),
    *(f"SEM-NET-{number:03d}" for number in range(13, 21)),
    *(f"SEM-CAL-{number:03d}" for number in range(21, 31)),
    *(f"SEM-MIL-{number:03d}" for number in range(31, 35)),
    *(f"SEM-CON-{number:03d}" for number in range(35, 39)),
    *(f"SEM-STA-{number:03d}" for number in range(39, 47)),
    *(f"SEM-FLT-{number:03d}" for number in range(47, 49)),
    *(f"SEM-DET-{number:03d}" for number in range(49, 51)),
)

EXPECTED_FILENAME_BY_ID = {
    case_id: f"{case_id.lower()}.json" for case_id in EXPECTED_CASE_IDS
}
EXPECTED_ID_BY_FILENAME = {
    filename: case_id for case_id, filename in EXPECTED_FILENAME_BY_ID.items()
}

# Raw byte identities are deliberately independent of the fixture-supplied
# expected values.  They prevent an alternate, internally consistent corpus
# from being labelled as the preregistered suite.
EXPECTED_FIXTURE_SHA256_BY_FILENAME = {
    "sem-rel-001.json": "36d65aa5a19ba602439b08248efa3f8a9965fee1cf98bbb19744e4153aef179e",
    "sem-rel-002.json": "15b1a60e5759673a95b5ac1dfb347281d6ee9fe03cf2e5db4a247a56ee4df666",
    "sem-rel-003.json": "589c43c7f16080321a6a4f872e5ad49bb4b2e0fb3442e1e986b014bafffb42dc",
    "sem-rel-004.json": "a96c684f71581e415a5b299edc94a49cfbde2d4e56cb628d71da7cb61a4c5f31",
    "sem-rel-005.json": "6a26bd0e826b7c61c73def94f2148f8907c3831040874a7a0b81c8a4c738e6bc",
    "sem-rel-006.json": "97280f6a3d1765a8c0356a79e09e5fb42dcfa8b589fe5111e25cc7258f21db42",
    "sem-rel-007.json": "bb5d9ebd5b1e95ada392ab012b8cbc485e517532b9f7b85408a2577def6070f0",
    "sem-rel-008.json": "962b2afab50e152be7133374455ae99d807d1923f216e0381abc10ce21d72c3f",
    "sem-rel-009.json": "7da1850a63a44d540b24f429a000c5fb2a0fb7b308706e937bd5152955d3128d",
    "sem-rel-010.json": "d6d22f0b14374448496b8bda34d2b0d6ed649b810b479cab45892ccc08172a25",
    "sem-rel-011.json": "db1368a251eddd1a112c261f7576f69956c01b9f0c001037aef9822312af61fe",
    "sem-rel-012.json": "0fab03e3f1b9da332021654c78aa191df5f4f3bcae9abb3cb196157650fbfff3",
    "sem-net-013.json": "42014b154954cf609990505ec5ab94dad86645d80cc46d1c52e35d691351b06d",
    "sem-net-014.json": "e20fb5007647fadd1389fe120cc24ff7c3431b85a3efb8e1e5f68a5953dc9b5e",
    "sem-net-015.json": "f85f4d91e180d131aa08e7890df558a92e21fe372b2e4ebc4766347c76344609",
    "sem-net-016.json": "8a481eb6670e79c9ce72ebc49b0a6bfaf7e0e0445865853fb5f0ece462844f06",
    "sem-net-017.json": "414d24d155fc2dbe9a852854242ab7ed65bd6fc2c8ece9148094222714240f48",
    "sem-net-018.json": "c77b088aa8569f06fb0da051580ce3d3fa1e0be4bdce26947deb57ee8251bd36",
    "sem-net-019.json": "4983f5a742d916f869941df2ac5b1c99e2379a5edbab1da385298d88a0ae2bb1",
    "sem-net-020.json": "3a46ae42bb7cfa3bade65d8d6909feca6820ef20fcd4040a5bb2cb8fa4f836ff",
    "sem-cal-021.json": "2cfe96c7e1d72611f0f5377c41fd140a1477ce494360108f9f6517cffcd42fb9",
    "sem-cal-022.json": "9d7db2cfec1fcf6843adb11e5555e59b0d23cd2268ff3196ceaeaed15251a1d6",
    "sem-cal-023.json": "5c9196a20480710cd93cda832261b14d7b834fbe481c742ed56850ac89d4e184",
    "sem-cal-024.json": "ebdc57545786bb9d6b542ff74a39e506be4105761c6b5f4590b384492a1c9b05",
    "sem-cal-025.json": "e468e532e5b8830402325f01aff5c0bf79e4be2230e400b61a7fdf79c7caae2a",
    "sem-cal-026.json": "1c77d23d5bdd9ff3338277e6158e8ae4ad6d8836ec3ece47faaecd4c2419b7ee",
    "sem-cal-027.json": "af2a6c0379416cf8bd87160538eae55cfc9426ef5c53bbecb23a8bde90e4f215",
    "sem-cal-028.json": "9443140d88b707f9194e271ad3021764c20bff621d89c0055035af67e20b1b36",
    "sem-cal-029.json": "85f60b145fc56518a1f18a8ee6e386eacd88afafe96df5aea3ec6df8f9bc6f0a",
    "sem-cal-030.json": "a64a9ca61d151521e757861e0425eb8b0140d8ddcbae7daa50cd91aed1bb71d4",
    "sem-mil-031.json": "306dbb4cdaac022a93b343e6f2adcab0e12a7fff560ce3be1a9ea923e482888e",
    "sem-mil-032.json": "5334ad3cb854fb4e4f682da29d8b7559db14a1f1a23893bbea1593fda80938f5",
    "sem-mil-033.json": "39b128af271c1a227c7e1b71154d7fc0fdb387f1001f372cab80f5d19201b73c",
    "sem-mil-034.json": "21a5d910f9af9ee1371be422d79dac4f209e4e7fc53f754c31744e05ef599769",
    "sem-con-035.json": "13c796f9f3fe4f00771f606da17b73b658d2963e105d3169591758b6c6105f96",
    "sem-con-036.json": "8b7236d1a48961ee8f28153feb34a8966bbeefceebd7dc8970e828453ff5e704",
    "sem-con-037.json": "ff296e7967aad590f493e2a70f4d4ad9c8643348ea3e981adeed94f75c5f0a04",
    "sem-con-038.json": "ea5eec37d2cb9f70e24c13f7463131aca1d2ead8fcbea5dc327d1a80c219356d",
    "sem-sta-039.json": "3077f870cbb9a06342c58c094c20d4431200bb71a51dcbebf2820abbd380ab91",
    "sem-sta-040.json": "b0d0655fcac346a5bb45d9366709aa34c915fa488342ed5e36fe93022c60af21",
    "sem-sta-041.json": "d40bc5e03815e12590daf5d5adb7c8f186cb3cf8dcf003d1cc3a7b5425458c5c",
    "sem-sta-042.json": "797bc62bed05ba086825c7b684c0250f9ced3f9332688e5ac7b079bbdd5aa6c2",
    "sem-sta-043.json": "f1e31260dce2b140afdc62812dd24be974f9a6c6d3f2cbaae34824c997e0464f",
    "sem-sta-044.json": "86b0f560d7bda7b75713d66ac7b6831b5fa84a5c29bc2a38ff8af3d2a4a3b71c",
    "sem-sta-045.json": "ae2934a259c316d68a806d6946ca7d1eb408de988862281a08088982d0eb3e02",
    "sem-sta-046.json": "2375d4696217211d80a38a69745b3ae995f19dc4d496ca35680b36bb5f9b2c23",
    "sem-flt-047.json": "69543190d25563a078dacf887450101b528a2982248bbaba16c3d32e5c2eb6a4",
    "sem-flt-048.json": "4312def4cd4a1041a381831e0404f77074870cf97cdbbcc871ad8a3b95d05630",
    "sem-det-049.json": "1b643ba35dd3883c417be9e65fe4df7bf7aaeba9de489e459517e2fafba91bcf",
    "sem-det-050.json": "97de709ca9b762a9a793ec84e7a0a8fa2a916449e29d1c96dd7195fe33554a12",
}

EXPECTED_CATALOGUE_SHA256 = (
    "a43d440c86562262d327fde17f7b8ad0760e131efb23d16c4b57b731d6beadf0"
)
