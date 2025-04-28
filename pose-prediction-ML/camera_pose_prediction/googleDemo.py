import cv2
import mediapipe as mp
import pyvirtualcam


# Initialize MediaPipe Pose
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.5, model_complexity=1)
mp_drawing = mp.solutions.drawing_utils

# Initialize MediaPipe Hands
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(static_image_mode=False, min_detection_confidence=0.5, min_tracking_confidence=0.5, max_num_hands=2, model_complexity=1)
mp_hs_drawing = mp.solutions.drawing_utils

# Capture video from webcam
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise IOError("Cannot open webcam")

width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fmt = pyvirtualcam.PixelFormat.BGR


while True:
    success, image = cap.read()
    if not success:
        print("Ignoring empty camera frame.")
        continue

    # Flip horizontally and convert BGR to RGB
    image = cv2.cvtColor(cv2.flip(image, 1), cv2.COLOR_BGR2RGB)

    image.flags.writeable = False
    results = pose.process(image)
    results_hands = hands.process(image)

    # Draw the annotations
    image.flags.writeable = True
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    
    if results.pose_landmarks:
        mp_drawing.draw_landmarks(image, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)

    if results_hands.multi_hand_landmarks:
        for hand_landmarks in results_hands.multi_hand_landmarks:
            mp_hs_drawing.draw_landmarks(image, hand_landmarks, mp_hands.HAND_CONNECTIONS)

    cv2.imshow('MediaPipe Pose and Hands', image)
    # cam.send(image)
    # cam.sleep_until_next_frame()

    if cv2.waitKey(5) & 0xFF == 27:  # Press ESC to exit
        break

pose.close()
hands.close()
cap.release()
cv2.destroyAllWindows()
