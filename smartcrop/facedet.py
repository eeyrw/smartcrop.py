import os
import numpy as np
import cv2 as cv


# Check OpenCV version
assert cv.__version__ >= "4.8.0", \
    "Please install latest opencv-python to try this demo: python3 -m pip install --upgrade opencv-python"


class YuNet:
    def __init__(self, modelPath, inputSize=[320, 320], confThreshold=0.6, nmsThreshold=0.3, topK=5000, backendId=0, targetId=0):
        self._modelPath = modelPath
        self._inputSize = tuple(inputSize)  # [w, h]
        self._confThreshold = confThreshold
        self._nmsThreshold = nmsThreshold
        self._topK = topK
        self._backendId = backendId
        self._targetId = targetId

        self._model = cv.FaceDetectorYN.create(
            model=self._modelPath,
            config="",
            input_size=self._inputSize,
            score_threshold=self._confThreshold,
            nms_threshold=self._nmsThreshold,
            top_k=self._topK,
            backend_id=self._backendId,
            target_id=self._targetId)

    @property
    def name(self):
        return self.__class__.__name__

    def setBackendAndTarget(self, backendId, targetId):
        self._backendId = backendId
        self._targetId = targetId
        self._model = cv.FaceDetectorYN.create(
            model=self._modelPath,
            config="",
            input_size=self._inputSize,
            score_threshold=self._confThreshold,
            nms_threshold=self._nmsThreshold,
            top_k=self._topK,
            backend_id=self._backendId,
            target_id=self._targetId)

    def setInputSize(self, input_size):
        self._model.setInputSize(tuple(input_size))

    def infer(self, image):
        # Forward
        faces = self._model.detect(image)
        return np.array([]) if faces[1] is None else faces[1]


class FaceDetector:
    def __init__(self, backend_target=0,
                 conf_threshold=0.8,
                 nms_threshold=0.3,
                 top_k=5000) -> None:
        # Valid combinations of backends and targets
        backend_target_pairs = [
            [cv.dnn.DNN_BACKEND_OPENCV, cv.dnn.DNN_TARGET_CPU],
            [cv.dnn.DNN_BACKEND_CUDA, cv.dnn.DNN_TARGET_CUDA],
            [cv.dnn.DNN_BACKEND_CUDA, cv.dnn.DNN_TARGET_CUDA_FP16],
            [cv.dnn.DNN_BACKEND_TIMVX, cv.dnn.DNN_TARGET_NPU],
            [cv.dnn.DNN_BACKEND_CANN, cv.dnn.DNN_TARGET_NPU]
        ]

        backend_id = backend_target_pairs[backend_target][0]
        target_id = backend_target_pairs[backend_target][1]

        # Instantiate YuNet
        here = os.path.abspath(os.path.dirname(__file__))
        self.model = YuNet(modelPath=os.path.join(here, 'face_detection_yunet_2023mar.onnx'),
                           inputSize=[320, 320],
                           confThreshold=conf_threshold,
                           nmsThreshold=nms_threshold,
                           topK=top_k,
                           backendId=backend_id,
                           targetId=target_id)

    def visualize(self, image, results, box_color=(0, 255, 0), text_color=(0, 0, 255), fps=None):
        output = image.copy()
        landmark_color = [
            (255, 0, 0),  # right eye
            (0, 0, 255),  # left eye
            (0, 255, 0),  # nose tip
            (255, 0, 255),  # right mouth corner
            (0, 255, 255)  # left mouth corner
        ]

        if fps is not None:
            cv.putText(output, 'FPS: {:.2f}'.format(fps), (0, 15),
                       cv.FONT_HERSHEY_SIMPLEX, 0.5, text_color)

        for det in results:
            bbox = det[0:4].astype(np.int32)
            cv.rectangle(output, (bbox[0], bbox[1]), (bbox[0] +
                         bbox[2], bbox[1] + bbox[3]), box_color, 2)

            conf = det[-1]
            cv.putText(output, '{:.4f}'.format(conf),
                       (bbox[0], bbox[1] + 12), cv.FONT_HERSHEY_DUPLEX, 0.5, text_color)

            landmarks = det[4:14].astype(np.int32).reshape((5, 2))
            for idx, landmark in enumerate(landmarks):
                cv.circle(output, landmark, 2, landmark_color[idx], 2)

        return output

    def detect(self, img, outputVisualResult=None):
        # If input is an image
        image = cv.cvtColor(np.array(img), cv.COLOR_RGB2BGR)
        h, w, _ = image.shape

        # Inference
        self.model.setInputSize([w, h])
        results = self.model.infer(image)

        # Print results
        print('{} faces detected.'.format(results.shape[0]))
        for idx, det in enumerate(results):
            print('{}: {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f} {:.0f}'.format(
                idx, *det[:-1])
            )

        # Draw results on the input image
        if outputVisualResult:
            image = self.visualize(image, results)
            print('Resutls saved to %s\n', outputVisualResult)
            cv.imwrite(outputVisualResult, image)

        return results


if __name__ == '__main__':
    dtr = FaceDetector()
    dtr.detect('/home/songfuqiang/smartcrop.py/tests/images/65309527.jpg')
