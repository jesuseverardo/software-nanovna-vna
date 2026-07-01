/*
  Control combinado:
  - Atenuador programable HMC742
  - Switches RF (TX y RX)
  
  Comandos por Serial (9600 baudios):
    SW0           -> TX=LOW,  RX=LOW
    SW1           -> TX=HIGH, RX=HIGH
    TX0           -> TX=LOW
    TX1           -> TX=HIGH
    RX0           -> RX=LOW
    RX1           -> RX=HIGH
    0..63         -> Atenuación en pasos de 0.5 dB
    ATT n         -> Atenuación n (0..63)

  NOTA:
  - 63 pasos = 31.5 dB
  - La lógica del atenuador se conserva de la siguiente manera
      bit = 1  -> salida LOW
      bit = 0  -> salida HIGH
*/

const uint8_t TX_SWITCH_PINS[2] = {2, 10};
const uint8_t RX_SWITCH_PINS[2] = {3, 11};

const uint8_t pinV1 = 4; // 16 dB
const uint8_t pinV2 = 5; // 8 dB
const uint8_t pinV3 = 6; // 4 dB
const uint8_t pinV4 = 7; // 2 dB
const uint8_t pinV5 = 8; // 1 dB
const uint8_t pinV6 = 9; // 0.5 dB

const uint8_t ledPin = 13;

// pinMap[0] = 0.5 dB, pinMap[5] = 16 dB
const uint8_t pinMap[6] = {pinV6, pinV5, pinV4, pinV3, pinV2, pinV1};

// Buffer serial
static char lineBuf[40];
static uint8_t idx = 0;

// Estado actual
int currentSteps = 0;
bool txState = LOW;
bool rxState = LOW;

void toUpperCase(char* s) {
  while (*s) {
    if (*s >= 'a' && *s <= 'z') *s = *s - ('a' - 'A');
    s++;
  }
}

void trimString(char* s) {
  char* start = s;
  while (*start == ' ' || *start == '\t' || *start == '\r' || *start == '\n') {
    start++;
  }

  if (start != s) {
    memmove(s, start, strlen(start) + 1);
  }

  int len = strlen(s);
  while (len > 0 && (s[len - 1] == ' ' || s[len - 1] == '\t' || s[len - 1] == '\r' || s[len - 1] == '\n')) {
    s[len - 1] = '\0';
    len--;
  }
}

float stepsToDb(int steps) {
  return steps * 0.5f;
}

void setTX(bool state) {
  txState = state;
  for (uint8_t i = 0; i < 2; i++) {
    digitalWrite(TX_SWITCH_PINS[i], txState ? HIGH : LOW);
  }
}

void setRX(bool state) {
  rxState = state;
  for (uint8_t i = 0; i < 2; i++) {
    digitalWrite(RX_SWITCH_PINS[i], rxState ? HIGH : LOW);
  }
}

void setBothSwitches(bool state) {
  setTX(state);
  setRX(state);
}

// Atenuador
void setAttenuationSteps(int steps) {
  if (steps < 0) steps = 0;
  if (steps > 63) steps = 63;

  currentSteps = steps;

  for (int i = 0; i < 6; i++) {
    bool bitSet = (steps >> i) & 0x01;
    digitalWrite(pinMap[i], bitSet ? LOW : HIGH);
  }

  Serial.print(F("OK ATT="));
  Serial.print(currentSteps);
  Serial.print(F(" ("));
  Serial.print(stepsToDb(currentSteps), 1);
  Serial.println(F(" dB)"));
}

// Estado
void printStatus() {
  Serial.print(F("STATUS | TX="));
  Serial.print(txState ? F("HIGH") : F("LOW"));
  Serial.print(F(" | RX="));
  Serial.print(rxState ? F("HIGH") : F("LOW"));
  Serial.print(F(" | ATT="));
  Serial.print(currentSteps);
  Serial.print(F(" ("));
  Serial.print(stepsToDb(currentSteps), 1);
  Serial.println(F(" dB)"));
}

void printHelp() {
  Serial.println(F("Comandos disponibles:"));
  Serial.println(F("  SW0      -> TX=LOW,  RX=LOW"));
  Serial.println(F("  SW1      -> TX=HIGH, RX=HIGH"));
  Serial.println(F("  TX0      -> TX=LOW"));
  Serial.println(F("  TX1      -> TX=HIGH"));
  Serial.println(F("  RX0      -> RX=LOW"));
  Serial.println(F("  RX1      -> RX=HIGH"));
  Serial.println(F("  0..63    -> Atenuacion en pasos de 0.5 dB"));
  Serial.println(F("  ATT n    -> Atenuacion n (0..63)"));
  Serial.println(F("  H        -> LED ON"));
  Serial.println(F("  L        -> LED OFF"));
  Serial.println(F("  PING     -> PONG"));
  Serial.println(F("  STATUS   -> Estado actual"));
  Serial.println(F("  HELP     -> Esta ayuda"));
}

void handleLine(char* s) {
  trimString(s);
  toUpperCase(s);

  if (strlen(s) == 0) return;

  // Comandos switches conjuntos
  if (strcmp(s, "SW0") == 0) {
    setBothSwitches(LOW);
    Serial.println(F("OK SW0"));
    return;
  }

  if (strcmp(s, "SW1") == 0) {
    setBothSwitches(HIGH);
    Serial.println(F("OK SW1"));
    return;
  }

  if (strcmp(s, "TX0") == 0) {
    setTX(LOW);
    Serial.println(F("OK TX0"));
    return;
  }

  if (strcmp(s, "TX1") == 0) {
    setTX(HIGH);
    Serial.println(F("OK TX1"));
    return;
  }

  if (strcmp(s, "RX0") == 0) {
    setRX(LOW);
    Serial.println(F("OK RX0"));
    return;
  }

  if (strcmp(s, "RX1") == 0) {
    setRX(HIGH);
    Serial.println(F("OK RX1"));
    return;
  }

  if (strcmp(s, "H") == 0) {
    digitalWrite(ledPin, HIGH);
    Serial.println(F("OK LED HIGH"));
    return;
  }

  if (strcmp(s, "L") == 0) {
    digitalWrite(ledPin, LOW);
    Serial.println(F("OK LED LOW"));
    return;
  }

  if (strcmp(s, "PING") == 0) {
    Serial.println(F("PONG"));
    return;
  }

  if (strcmp(s, "STATUS") == 0) {
    printStatus();
    return;
  }

  if (strcmp(s, "HELP") == 0) {
    printHelp();
    return;
  }

  if (strncmp(s, "ATT ", 4) == 0) {
    long v = atol(s + 4);
    setAttenuationSteps((int)v);
    return;
  }

  char* endp;
  long v = strtol(s, &endp, 10);
  if (*endp == '\0') {
    setAttenuationSteps((int)v);
    return;
  }

  Serial.println(F("ERR BAD_CMD"));
}

void setup() {
  // Switches
  for (uint8_t i = 0; i < 2; i++) {
    pinMode(TX_SWITCH_PINS[i], OUTPUT);
    pinMode(RX_SWITCH_PINS[i], OUTPUT);
  }

  // Atenuador
  pinMode(pinV1, OUTPUT);
  pinMode(pinV2, OUTPUT);
  pinMode(pinV3, OUTPUT);
  pinMode(pinV4, OUTPUT);
  pinMode(pinV5, OUTPUT);
  pinMode(pinV6, OUTPUT);

  // LED
  pinMode(ledPin, OUTPUT);

  // Estados iniciales
  setBothSwitches(LOW);

  digitalWrite(pinV1, HIGH);
  digitalWrite(pinV2, HIGH);
  digitalWrite(pinV3, HIGH);
  digitalWrite(pinV4, HIGH);
  digitalWrite(pinV5, HIGH);
  digitalWrite(pinV6, HIGH);

  digitalWrite(ledPin, LOW);

  Serial.begin(9600);
  delay(200);

  Serial.println(F("ARDUINO_READY"));
  printStatus();
  printHelp();
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\n') {
      lineBuf[idx] = '\0';
      handleLine(lineBuf);
      idx = 0;
      continue;
    }

    if (c == '\r') continue;

    if (idx < sizeof(lineBuf) - 1) {
      lineBuf[idx++] = c;
    } else {
      idx = 0;
      Serial.println(F("ERR LINE_TOO_LONG"));
    }
  }
}